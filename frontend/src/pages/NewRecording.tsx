import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import { fmtBytes } from "../lib/format";
import type { Patient, Recording } from "../lib/types";
import { useApi } from "../lib/useApi";
import { clipFraction, encodeWav, levelDbfs } from "../lib/wav";
import { Icon, Notice, PageHeader } from "../components/ui";

const MAX_SECONDS = 120;
const TARGET_SECONDS = 20;

type Capture = { blob: Blob; name: string; source: "mic" | "file"; seconds?: number };

function useRecorder() {
  const [state, setState] = useState<"idle" | "requesting" | "recording" | "denied" | "unsupported">("idle");
  const [level, setLevel] = useState(-120);
  const [clipping, setClipping] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const chunks = useRef<Float32Array[]>([]);
  const ctxRef = useRef<AudioContext | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const procRef = useRef<ScriptProcessorNode | null>(null);
  const live = useRef<Float32Array>(new Float32Array(0));
  const startAt = useRef(0);
  const rateRef = useRef(48000);

  const cleanup = () => {
    procRef.current?.disconnect();
    streamRef.current?.getTracks().forEach((t) => t.stop());
    ctxRef.current?.close().catch(() => undefined);
    procRef.current = null;
    streamRef.current = null;
    ctxRef.current = null;
  };
  useEffect(() => cleanup, []);

  async function start() {
    if (!navigator.mediaDevices?.getUserMedia) {
      setState("unsupported");
      return;
    }
    setState("requesting");
    try {
      // Disable browser voice processing: echo cancellation, noise suppression and AGC distort heart sounds.
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false, channelCount: 1 },
      });
      const ctx = new AudioContext();
      const src = ctx.createMediaStreamSource(stream);
      const proc = ctx.createScriptProcessor(4096, 1, 1);
      chunks.current = [];
      rateRef.current = ctx.sampleRate;
      proc.onaudioprocess = (e) => {
        const block = new Float32Array(e.inputBuffer.getChannelData(0));
        chunks.current.push(block);
        live.current = block;
        setLevel(levelDbfs(block));
        if (clipFraction(block) > 0.001) setClipping(true);
        const secs = (performance.now() - startAt.current) / 1000;
        setElapsed(secs);
      };
      src.connect(proc);
      proc.connect(ctx.destination);
      ctxRef.current = ctx;
      streamRef.current = stream;
      procRef.current = proc;
      startAt.current = performance.now();
      setClipping(false);
      setElapsed(0);
      setState("recording");
    } catch {
      setState("denied");
    }
  }

  function stop(): Capture | null {
    const rate = rateRef.current;
    const data = chunks.current;
    cleanup();
    setState("idle");
    if (!data.length) return null;
    const seconds = data.reduce((n, c) => n + c.length, 0) / rate;
    return { blob: encodeWav(data, rate), name: `recording-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.wav`, source: "mic", seconds };
  }

  return { state, level, clipping, elapsed, start, stop, live, sampleRate: rateRef };
}

function LiveScope({ live, active }: { live: React.MutableRefObject<Float32Array>; active: boolean }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    if (!active) return;
    let raf = 0;
    const draw = () => {
      const c = ref.current;
      const ctx = c?.getContext("2d");
      if (c && ctx) {
        const w = (c.width = c.clientWidth);
        const h = (c.height = c.clientHeight);
        ctx.clearRect(0, 0, w, h);
        ctx.strokeStyle = "#5eead4";
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        const d = live.current;
        for (let i = 0; i < d.length; i += 4) {
          const x = (i / d.length) * w;
          const y = h / 2 - d[i] * h * 0.45;
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.stroke();
      }
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [active, live]);
  return <canvas ref={ref} className="h-24 w-full rounded-md bg-navy-900" aria-label="Live input waveform" role="img" />;
}

export default function NewRecording() {
  const nav = useNavigate();
  const [params] = useSearchParams();
  const { data: patients, setData: setPatients } = useApi<Patient[]>("/patients");
  const [patientId, setPatientId] = useState<string>(params.get("patient") ?? "");
  const [device, setDevice] = useState("electronic_stethoscope");
  const [site, setSite] = useState("mitral");
  const [env, setEnv] = useState("clinic_quiet");
  const [urgent, setUrgent] = useState(false);
  const [consent, setConsent] = useState(false);
  const [capture, setCapture] = useState<Capture | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<{ msg: string; rerecord?: boolean } | null>(null);
  const rec = useRecorder();

  // Auto-stop at the maximum duration so recordings stay within the quality gate's limits.
  useEffect(() => {
    if (rec.state === "recording" && rec.elapsed >= MAX_SECONDS) {
      const c = rec.stop();
      if (c) setCapture(c);
    }
  }, [rec, rec.elapsed, rec.state]);

  useEffect(() => {
    if (!capture) return setPreviewUrl(null);
    const u = URL.createObjectURL(capture.blob);
    setPreviewUrl(u);
    return () => URL.revokeObjectURL(u);
  }, [capture]);

  async function createPatient() {
    const p = await api.post<Patient>("/patients", {});
    setPatients([p, ...(patients ?? [])]);
    setPatientId(String(p.id));
  }

  async function submit() {
    if (!capture || !patientId || !consent) return;
    setBusy(true);
    setErr(null);
    const fd = new FormData();
    fd.append("file", capture.blob, capture.name);
    fd.append("consent_confirmed", "true");
    fd.append("device_type", device);
    fd.append("auscultation_site", site);
    fd.append("environment", env);
    fd.append("recorded_at", new Date().toISOString());
    try {
      const r = await api.post<Recording>(`/patients/${patientId}/recordings`, fd);
      nav(`/recordings/${r.id}`);
    } catch (e) {
      const d = e instanceof ApiError ? (e.detail as { recommend_rerecord?: boolean } | null) : null;
      setErr({ msg: (e as Error).message, rerecord: !!d?.recommend_rerecord });
    } finally {
      setBusy(false);
    }
  }

  const levelPct = Math.max(0, Math.min(100, ((rec.level + 60) / 60) * 100));
  const ready = !!capture && !!patientId && consent;

  return (
    <>
      <PageHeader title="New recording" subtitle="Capture or import a heart-sound recording. Quality is checked before any analysis." />
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <section className="card">
            <div className="card-h">
              <h2 className="h-title">1 · Patient and context</h2>
            </div>
            <div className="card-b grid gap-4 sm:grid-cols-2">
              <div className="sm:col-span-2">
                <label className="label" htmlFor="patient">
                  Patient
                </label>
                <div className="flex gap-2">
                  <select id="patient" className="input" value={patientId} onChange={(e) => setPatientId(e.target.value)}>
                    <option value="">Select patient…</option>
                    {(patients ?? []).map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.pseudonym}
                        {p.external_ref ? ` · ${p.external_ref}` : ""}
                        {p.is_synthetic ? " (demo)" : ""}
                      </option>
                    ))}
                  </select>
                  <button type="button" className="btn-ghost shrink-0" onClick={createPatient}>
                    New patient
                  </button>
                </div>
              </div>
              <div>
                <label className="label" htmlFor="device">
                  Recording device
                </label>
                <select id="device" className="input" value={device} onChange={(e) => setDevice(e.target.value)}>
                  <option value="electronic_stethoscope">Electronic stethoscope</option>
                  <option value="smartphone_mic">Smartphone microphone</option>
                  <option value="external_mic">External microphone</option>
                  <option value="other">Other</option>
                </select>
              </div>
              <div>
                <label className="label" htmlFor="site">
                  Auscultation site
                </label>
                <select id="site" className="input" value={site} onChange={(e) => setSite(e.target.value)}>
                  {["aortic", "pulmonic", "tricuspid", "mitral", "other"].map((s) => (
                    <option key={s} value={s}>
                      {s[0].toUpperCase() + s.slice(1)}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="label" htmlFor="env">
                  Environment
                </label>
                <select id="env" className="input" value={env} onChange={(e) => setEnv(e.target.value)}>
                  <option value="clinic_quiet">Clinic — quiet room</option>
                  <option value="clinic_busy">Clinic — busy</option>
                  <option value="ward">Ward</option>
                  <option value="home">Home</option>
                  <option value="other">Other</option>
                </select>
              </div>
              <label className="flex items-start gap-2 self-end text-sm">
                <input type="checkbox" className="mt-1 h-4 w-4" checked={urgent} onChange={(e) => setUrgent(e.target.checked)} />
                Patient reports severe or urgent symptoms
              </label>
              {urgent && (
                <div className="sm:col-span-2">
                  <Notice tone="flag" title="Follow urgent-care pathways now">
                    Symptoms such as chest pain, fainting, severe breathlessness or palpitations with dizziness need immediate clinical
                    assessment. Do not delay care to obtain or analyse a recording — this tool cannot rule out an emergency.
                  </Notice>
                </div>
              )}
            </div>
          </section>

          <section className="card">
            <div className="card-h">
              <h2 className="h-title">2 · Capture audio</h2>
            </div>
            <div className="card-b space-y-4">
              {rec.state === "recording" ? (
                <div className="space-y-3">
                  <LiveScope live={rec.live} active />
                  <div className="flex items-center gap-3">
                    <span className="inline-flex items-center gap-2 text-sm font-medium text-navy-800">
                      <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-teal-500" /> Recording {rec.elapsed.toFixed(0)} s
                      <span className="text-slate-500">/ target {TARGET_SECONDS} s</span>
                    </span>
                  </div>
                  <div>
                    <div className="flex justify-between text-xs text-slate-500">
                      <span>Input level</span>
                      <span>{rec.level.toFixed(0)} dBFS</span>
                    </div>
                    <div className="mt-1 h-2 rounded bg-slate-100" role="meter" aria-valuemin={-60} aria-valuemax={0} aria-valuenow={Math.round(rec.level)} aria-label="Input level">
                      <div className={`h-2 rounded ${rec.clipping ? "bg-issue-700" : "bg-teal-500"}`} style={{ width: `${levelPct}%` }} />
                    </div>
                    {rec.clipping && <p className="mt-1 text-xs text-issue-700">Clipping detected — reduce gain or pressure and consider re-recording.</p>}
                    {rec.level < -55 && rec.elapsed > 2 && <p className="mt-1 text-xs text-issue-700">Very low input — check placement and connection.</p>}
                  </div>
                  <button
                    className="btn-primary"
                    onClick={() => {
                      const c = rec.stop();
                      if (c) setCapture(c);
                    }}
                  >
                    Stop recording
                  </button>
                </div>
              ) : (
                <div className="flex flex-col gap-3 sm:flex-row">
                  <button className="btn-teal" onClick={() => { setCapture(null); rec.start(); }} disabled={rec.state === "requesting"}>
                    <Icon name="mic" /> {capture ? "Record again" : "Start recording"}
                  </button>
                  <label className="btn-ghost cursor-pointer">
                    Import audio file
                    <input
                      type="file"
                      accept="audio/*,.wav,.flac,.ogg,.webm,.mp3,.m4a"
                      className="sr-only"
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (f) setCapture({ blob: f, name: f.name, source: "file" });
                        e.target.value = "";
                      }}
                    />
                  </label>
                </div>
              )}
              {rec.state === "denied" && <Notice tone="issue">Microphone permission was denied. Allow microphone access in your browser settings, or import a file.</Notice>}
              {rec.state === "unsupported" && <Notice tone="issue">This browser cannot record audio. Import a WAV file instead.</Notice>}
              {capture && previewUrl && rec.state !== "recording" && (
                <div className="rounded-lg bg-slate-50 p-3">
                  <p className="text-sm font-medium">{capture.name}</p>
                  <p className="text-xs text-slate-500">
                    {capture.source === "mic" ? `Microphone · ${capture.seconds?.toFixed(1)} s · WAV` : "Imported file"} · {fmtBytes(capture.blob.size)}
                  </p>
                  <audio controls src={previewUrl} className="mt-2 w-full" aria-label="Preview recording" />
                </div>
              )}
            </div>
          </section>

          <section className="card">
            <div className="card-h">
              <h2 className="h-title">3 · Consent and submit</h2>
            </div>
            <div className="card-b space-y-4">
              <label className="flex items-start gap-2 text-sm">
                <input type="checkbox" className="mt-1 h-4 w-4" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
                <span>
                  I confirm the patient (or their authorised representative) has consented to this heart-sound recording being stored and
                  analysed for the purposes described in the privacy notice (consent v1).
                </span>
              </label>
              {err && (
                <Notice tone="issue" title={err.rerecord ? "Recording could not be used — please record again" : "Upload failed"}>
                  {err.msg}
                </Notice>
              )}
              <button className="btn-primary w-full sm:w-auto" disabled={!ready || busy} onClick={submit}>
                {busy ? "Uploading and checking quality…" : "Upload and analyse"}
              </button>
              {!ready && <p className="text-xs text-slate-500">Select a patient, capture or import audio, and confirm consent to continue.</p>}
            </div>
          </section>
        </div>

        <aside className="space-y-4">
          <section className="card card-b space-y-2 text-sm">
            <h2 className="h-title">Recording guidance</h2>
            <ol className="list-decimal space-y-1 pl-5 text-slate-700">
              <li>Quiet room; pause conversation, fans and alarms.</li>
              <li>Patient still and breathing normally.</li>
              <li>Firm, steady contact on bare skin at the selected site.</li>
              <li>Record 15–30 s per site without moving the sensor.</li>
              <li>Watch the level meter: avoid clipping and very low input.</li>
            </ol>
          </section>
          <Notice tone="info" title="Hardware limitations">
            Smartphone and laptop microphones are designed for speech and are not equivalent to a medical-grade electronic stethoscope. They may
            miss low-frequency heart sounds entirely. Browser capture disables echo cancellation, noise suppression and automatic gain, but
            device-level processing can still alter the signal.
          </Notice>
        </aside>
      </div>
    </>
  );
}
