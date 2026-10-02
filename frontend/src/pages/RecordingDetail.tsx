import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, downloadFile } from "../lib/api";
import { fmtBytes, fmtDate, humanize } from "../lib/format";
import type { Recording } from "../lib/types";
import { useApi } from "../lib/useApi";
import { ModelPanel, QualityPanel, ReviewPanel } from "../components/AnalysisPanels";
import { SpectrogramView, Waveform } from "../components/SignalViews";
import { DemoBadge, ErrorBox, Loading, Notice, PageHeader, QualityBadge, ReviewBadge, TierBadge } from "../components/ui";

function useAudio(recordingId: number, available: boolean) {
  const [url, setUrl] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (!available) return;
    let u: string | null = null;
    api
      .blob(`/recordings/${recordingId}/audio`)
      .then((b) => {
        u = URL.createObjectURL(b);
        setUrl(u);
      })
      .catch((e: Error) => setErr(e.message));
    return () => {
      if (u) URL.revokeObjectURL(u);
    };
  }, [recordingId, available]);
  return { url, err };
}

export default function RecordingDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const rid = Number(id);
  const { data: r, error, loading, reload, setData } = useApi<Recording>(`/recordings/${rid}`);
  const { url, err: audioErr } = useAudio(rid, !!r?.audio_available);
  const audioRef = useRef<HTMLAudioElement>(null);
  const [progress, setProgress] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);

  if (loading && !r) return <Loading />;
  if (error) return <ErrorBox message={error} />;
  if (!r) return null;
  const a = r.analyses?.[r.analyses.length - 1];
  const s = a?.signal_summary;
  const dur = s?.duration_s ?? r.duration_s ?? 1;

  async function reanalyze() {
    setBusy("reanalyze");
    try {
      setData(await api.post<Recording>(`/recordings/${rid}/reanalyze`));
    } finally {
      setBusy(null);
    }
  }

  async function remove() {
    if (!confirm("Permanently delete this recording's audio? The audit trail is kept. This cannot be undone.")) return;
    setBusy("delete");
    try {
      await api.del(`/recordings/${rid}`);
      nav(`/patients/${r!.patient_id}`);
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <PageHeader
        title={`Audio analysis · ${r.patient_pseudonym}`}
        subtitle={
          <>
            <Link className="text-teal-700 underline" to={`/patients/${r.patient_id}`}>
              Patient record
            </Link>{" "}
            · {humanize(r.auscultation_site)} · {humanize(r.device_type)} · {humanize(r.environment)} · {fmtDate(r.recorded_at ?? r.created_at)}
          </>
        }
        actions={
          <>
            <button className="btn-ghost" onClick={() => downloadFile(`/recordings/${rid}/report?format=html`, `cardiolens-report-${r.patient_pseudonym}-${rid}.html`)}>
              Export report
            </button>
            <button className="btn-ghost" onClick={reanalyze} disabled={!r.audio_available || !!busy}>
              {busy === "reanalyze" ? "Analysing…" : "Re-run analysis"}
            </button>
            <button className="btn-danger" onClick={remove} disabled={!!busy}>
              Delete audio
            </button>
          </>
        }
      />
      <div className="mb-4 flex flex-wrap gap-2">
        {r.is_demo && <DemoBadge />}
        <QualityBadge status={r.quality_status} />
        <TierBadge tier={r.latest_result_tier} status={r.latest_model_status} />
        <ReviewBadge status={r.review_status} />
      </div>

      <div className="grid gap-6 xl:grid-cols-3">
        <div className="space-y-6 xl:col-span-2">
          <section className="card">
            <div className="card-h">
              <h2 className="h-title">Signal</h2>
              <span className="text-xs text-slate-500">
                {r.sample_rate} Hz · {r.channels} ch · {dur.toFixed(1)} s · {fmtBytes(r.size_bytes)}
              </span>
            </div>
            <div className="card-b space-y-3">
              {url ? (
                <audio
                  ref={audioRef}
                  controls
                  src={url}
                  className="w-full"
                  aria-label="Original recording playback"
                  onTimeUpdate={(e) => setProgress(e.currentTarget.currentTime / (e.currentTarget.duration || dur))}
                />
              ) : r.audio_available ? (
                audioErr ? <ErrorBox message={`Audio unavailable: ${audioErr}`} /> : <Loading label="Loading audio…" />
              ) : (
                <Notice tone="issue">Original audio has been deleted.</Notice>
              )}
              {s?.waveform && (
                <Waveform
                  data={s.waveform}
                  duration={dur}
                  progress={progress}
                  highlights={a?.model_output?.segments ?? []}
                  onSeek={(t) => {
                    if (audioRef.current) audioRef.current.currentTime = t;
                  }}
                />
              )}
              {s?.spectrogram && <SpectrogramView spec={s.spectrogram} progress={progress} />}
              {s && s.rms_dbfs !== undefined && (
                <dl className="grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
                  <div>
                    <dt className="text-slate-500">RMS / peak</dt>
                    <dd className="font-mono">
                      {s.rms_dbfs} / {s.peak_dbfs} dBFS
                    </dd>
                  </div>
                  {s.band_energy_fraction &&
                    Object.entries(s.band_energy_fraction).map(([k, v]) => (
                      <div key={k}>
                        <dt className="text-slate-500">Energy {k}</dt>
                        <dd className="font-mono">{(v * 100).toFixed(0)}%</dd>
                      </div>
                    ))}
                  {s.envelope_cycle_rate_per_min != null && (
                    <div className="col-span-2 sm:col-span-4">
                      <dt className="text-slate-500">Envelope repetition rate</dt>
                      <dd>
                        <span className="font-mono">{s.envelope_cycle_rate_per_min} /min</span>{" "}
                        <span className="text-slate-500">— {s.envelope_cycle_rate_note}</span>
                      </dd>
                    </div>
                  )}
                </dl>
              )}
              {!!s?.windows?.length && (
                <details className="text-sm">
                  <summary className="cursor-pointer text-slate-700">Per-segment quality ({s.windows.length} windows)</summary>
                  <div className="mt-2 overflow-x-auto">
                    <table className="table">
                      <thead>
                        <tr>
                          <th>Segment</th>
                          <th>SNR estimate</th>
                          <th>Regularity</th>
                        </tr>
                      </thead>
                      <tbody>
                        {s.windows.map((w) => (
                          <tr key={w.start_s}>
                            <td>
                              <button className="text-teal-700 underline" onClick={() => audioRef.current && (audioRef.current.currentTime = w.start_s)}>
                                {w.start_s}–{w.end_s} s
                              </button>
                            </td>
                            <td className="font-mono">{w.snr_db} dB</td>
                            <td className="font-mono">{w.periodicity}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </details>
              )}
            </div>
          </section>
          {a && <QualityPanel q={a.quality} />}
          {a && <ModelPanel a={a} />}
          {r.analyses && r.analyses.length > 1 && (
            <section className="card card-b text-sm">
              <h2 className="h-title mb-2">Analysis history</h2>
              <ul className="space-y-1 text-slate-600">
                {r.analyses.map((x) => (
                  <li key={x.id}>
                    {fmtDate(x.created_at)} · {x.pipeline_version} · quality {humanize(x.quality.overall)} · {humanize(x.model_status)}
                    {x.model_version ? ` · ${x.model_name} v${x.model_version}` : ""}
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
        <div className="space-y-6">
          <ReviewPanel recordingId={rid} reviews={r.reviews ?? []} onSaved={reload} />
          <section className="card card-b text-xs text-slate-500">
            <p>
              File: {r.original_filename} · SHA-256 <span className="break-all font-mono">{r.sha256}</span>
            </p>
            <p className="mt-1">Retained until {fmtDate(r.retention_until, false)} per organisation policy.</p>
          </section>
        </div>
      </div>
    </>
  );
}
