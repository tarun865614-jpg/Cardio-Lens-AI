import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from "recharts";
import { api } from "../lib/api";
import { fmtDate, fmtProportion, humanize } from "../lib/format";
import type { Dataset, EvaluationRun, MetricBlock, ModelVersion } from "../lib/types";
import { useApi } from "../lib/useApi";
import { Empty, ErrorBox, Loading, Notice, PageHeader } from "../components/ui";

const INK = "#1d3a63";
const GRID = "#e2e8f0";
const AXIS = { fontSize: 11, fill: "#64748b" };

type Tab = "evaluations" | "datasets" | "models";

export default function ResearchLab() {
  const [tab, setTab] = useState<Tab>("evaluations");
  return (
    <>
      <PageHeader
        title="Research lab"
        subtitle="Datasets, model versions and held-out evaluation. Metrics appear only when computed from labelled test data."
      />
      <Notice title="Methodology guard-rails">
        Evaluations are refused if they contain training/validation rows, a patient in more than one split, or a test patient present in the
        supplied training manifest. A dataset used for training cannot be marked as external validation. Internal results are never presented
        as clinical validation.
      </Notice>
      <div role="tablist" aria-label="Research sections" className="mt-5 flex gap-1 border-b border-slate-200">
        {(["evaluations", "datasets", "models"] as Tab[]).map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={tab === t}
            onClick={() => setTab(t)}
            className={`min-h-10 border-b-2 px-4 text-sm font-medium capitalize ${tab === t ? "border-teal-600 text-navy-900" : "border-transparent text-slate-500 hover:text-navy-800"}`}
          >
            {t}
          </button>
        ))}
      </div>
      <div className="mt-5">
        {tab === "evaluations" && <Evaluations />}
        {tab === "datasets" && <Datasets />}
        {tab === "models" && <Models />}
      </div>
    </>
  );
}

function Evaluations() {
  const runs = useApi<EvaluationRun[]>("/research/evaluations");
  const models = useApi<ModelVersion[]>("/research/models");
  const datasets = useApi<Dataset[]>("/research/datasets");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      const fd = new FormData(e.currentTarget);
      if (!(fd.get("training_manifest") as File)?.size) fd.delete("training_manifest");
      fd.set("is_external", fd.get("is_external") ? "true" : "false");
      await api.post("/research/evaluations", fd);
      e.currentTarget.reset();
      runs.reload();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <div className="lg:col-span-2">
        {runs.loading && !runs.data ? (
          <Loading />
        ) : runs.data?.length ? (
          <div className="card overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Model</th>
                  <th>Dataset</th>
                  <th>n (patients)</th>
                  <th>Sens.</th>
                  <th>Spec.</th>
                  <th>AUC</th>
                </tr>
              </thead>
              <tbody>
                {runs.data.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <Link className="text-teal-700 underline" to={`/research/evaluations/${r.id}`}>
                        #{r.id}
                      </Link>
                      <span className="ml-1 text-xs text-slate-500">{r.is_external ? "external" : "internal"}</span>
                    </td>
                    <td>
                      {r.model.name} v{r.model.version}
                    </td>
                    <td>{r.dataset.name}</td>
                    <td>
                      {r.n_recordings} ({r.n_patients})
                    </td>
                    {(["sensitivity", "specificity", "auc"] as const).map((k) => (
                      <td key={k} className="font-mono">
                        {r.headline[k] == null ? "—" : r.headline[k]!.toFixed(3)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty title="No model has been evaluated">
            Sensitivity, specificity, PPV/NPV, ROC/AUC, calibration and subgroup performance are shown here once predictions on a labelled,
            held-out test set are uploaded. Nothing is estimated or simulated in the meantime.
          </Empty>
        )}
      </div>
      <form onSubmit={submit} className="card card-b space-y-3 self-start">
        <h2 className="h-title">Upload held-out predictions</h2>
        <div>
          <label className="label" htmlFor="ev-model">
            Model version
          </label>
          <select id="ev-model" name="model_version_id" required className="input">
            <option value="">Select…</option>
            {models.data?.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name} v{m.version}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="ev-ds">
            Evaluation dataset
          </label>
          <select id="ev-ds" name="dataset_id" required className="input">
            <option value="">Select…</option>
            {datasets.data?.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="ev-thr">
            Decision threshold
          </label>
          <input id="ev-thr" name="threshold" type="number" step="0.01" min="0" max="1" defaultValue="0.5" className="input" />
        </div>
        <div>
          <label className="label" htmlFor="ev-pred">
            Predictions CSV
          </label>
          <input id="ev-pred" name="predictions" type="file" accept=".csv,text/csv" required className="text-sm" />
          <p className="mt-1 text-xs text-slate-500">Columns: recording_id, patient_id, label, score, split, quality_pass [+ device, environment, site, age_group, sex…]</p>
        </div>
        <div>
          <label className="label" htmlFor="ev-train">
            Training manifest CSV (leakage check)
          </label>
          <input id="ev-train" name="training_manifest" type="file" accept=".csv,text/csv" className="text-sm" />
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" name="is_external" /> Independent external dataset
        </label>
        {err && <p className="text-sm text-issue-700">{err}</p>}
        <button className="btn-primary w-full" disabled={busy || !models.data?.length || !datasets.data?.length}>
          {busy ? "Computing…" : "Compute metrics"}
        </button>
        {!models.data?.length && <p className="text-xs text-slate-500">Register a model version first.</p>}
      </form>
    </div>
  );
}

function Datasets() {
  const { data, loading, error, reload } = useApi<Dataset[]>("/research/datasets");
  const [show, setShow] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.currentTarget)) as Record<string, string>;
    try {
      await api.post("/research/datasets", f);
      setShow(false);
      reload();
    } catch (e) {
      setErr((e as Error).message);
    }
  }
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox message={error} />;
  return (
    <div className="space-y-4">
      <button className="btn-ghost" onClick={() => setShow((v) => !v)}>
        Register dataset
      </button>
      {show && (
        <form onSubmit={submit} className="card card-b grid gap-3 sm:grid-cols-2">
          {[
            ["name", "Name"],
            ["source_url", "Source URL"],
            ["license", "Licence (verified)"],
            ["permitted_use", "Permitted use"],
            ["provenance", "Provenance"],
            ["label_definitions", "Label definitions"],
            ["recording_devices", "Recording devices"],
            ["population", "Population"],
            ["limitations", "Known limitations"],
          ].map(([k, l]) => (
            <div key={k}>
              <label className="label" htmlFor={`ds-${k}`}>
                {l}
              </label>
              <input id={`ds-${k}`} name={k} className="input" required={["name", "license", "permitted_use", "provenance", "label_definitions"].includes(k)} />
            </div>
          ))}
          {err && <p className="text-sm text-issue-700 sm:col-span-2">{err}</p>}
          <button className="btn-primary sm:col-span-2">Save</button>
        </form>
      )}
      {data?.map((d) => (
        <article key={d.id} className="card card-b text-sm">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="font-semibold">{d.name}</h3>
            <span className={`badge ${d.is_downloaded ? "bg-teal-50 text-teal-700" : "bg-slate-100 text-slate-600"}`}>{d.is_downloaded ? "Available" : "Candidate — not downloaded"}</span>
          </div>
          {d.source_url && (
            <a className="text-xs text-teal-700 underline" href={d.source_url} target="_blank" rel="noreferrer noopener">
              {d.source_url}
            </a>
          )}
          <dl className="mt-3 grid gap-x-6 gap-y-2 sm:grid-cols-2">
            {(
              [
                ["Licence", d.license],
                ["Permitted use", d.permitted_use],
                ["Provenance", d.provenance],
                ["Labels", d.label_definitions],
                ["Devices", d.recording_devices],
                ["Population", d.population],
                ["Limitations", d.limitations],
                ["Size", d.n_recordings ? `${d.n_recordings} recordings / ${d.n_patients ?? "?"} patients` : "To be verified on download"],
              ] as const
            ).map(([k, v]) => (
              <div key={k}>
                <dt className="text-xs font-semibold uppercase tracking-wider text-slate-500">{k}</dt>
                <dd className="text-slate-700">{v || "—"}</dd>
              </div>
            ))}
          </dl>
        </article>
      ))}
    </div>
  );
}

function Models() {
  const { data, loading, error, reload } = useApi<ModelVersion[]>("/research/models");
  const [err, setErr] = useState<string | null>(null);
  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.currentTarget)) as Record<string, string>;
    try {
      await api.post("/research/models", {
        name: f.name,
        version: f.version,
        intended_use: f.intended_use,
        categories: f.categories.split(",").map((s) => ({ id: s.trim() })).filter((c) => c.id),
        training_datasets: f.training_datasets ? f.training_datasets.split(";").map((s) => s.trim()) : [],
        weights_sha256: f.weights_sha256 || null,
        validation_status: f.validation_status,
        validation_evidence: f.validation_evidence || null,
      });
      e.currentTarget.reset();
      setErr(null);
      reload();
    } catch (e) {
      setErr((e as Error).message);
    }
  }
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox message={error} />;
  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <div className="space-y-3 lg:col-span-2">
        {data?.length ? (
          data.map((m) => (
            <article key={m.id} className="card card-b text-sm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="font-semibold">
                  {m.name} <span className="font-mono text-slate-500">v{m.version}</span>
                </h3>
                <span className={`badge ${m.validation_status === "externally_validated" ? "bg-teal-600 text-white" : "bg-exp-50 text-exp-800"}`}>{humanize(m.validation_status)}</span>
              </div>
              <p className="mt-1 text-slate-700">{m.intended_use}</p>
              <p className="mt-1 text-xs text-slate-500">
                Categories: {m.categories.map((c) => c.label ?? c.id).join(", ")} · Trained on: {m.training_datasets.join("; ") || "—"} · registered{" "}
                {fmtDate(m.created_at, false)}
              </p>
              {m.validation_evidence && <p className="mt-1 text-xs">Evidence: {m.validation_evidence}</p>}
            </article>
          ))
        ) : (
          <Empty title="No model versions registered">The platform runs in research-demo mode until a model is registered, evaluated and configured.</Empty>
        )}
      </div>
      <form onSubmit={submit} className="card card-b space-y-3 self-start">
        <h2 className="h-title">Register model version</h2>
        {[
          ["name", "Name", true],
          ["version", "Version (immutable)", true],
          ["intended_use", "Intended use", true],
          ["categories", "Output categories (comma-separated ids)", true],
          ["training_datasets", "Training datasets (; separated)", false],
          ["weights_sha256", "Weights SHA-256", false],
        ].map(([k, l, req]) => (
          <div key={k as string}>
            <label className="label" htmlFor={`m-${k}`}>
              {l}
            </label>
            <input id={`m-${k}`} name={k as string} className="input" required={req as boolean} />
          </div>
        ))}
        <div>
          <label className="label" htmlFor="m-vs">
            Validation status
          </label>
          <select id="m-vs" name="validation_status" className="input">
            <option value="research_only">Research only</option>
            <option value="internally_evaluated">Internally evaluated</option>
            <option value="externally_validated">Externally validated (admin, evidence required)</option>
          </select>
        </div>
        <div>
          <label className="label" htmlFor="m-ev">
            Validation evidence (publication / report)
          </label>
          <input id="m-ev" name="validation_evidence" className="input" />
        </div>
        {err && <p className="text-sm text-issue-700">{err}</p>}
        <button className="btn-primary w-full">Register</button>
      </form>
    </div>
  );
}

function MetricTable({ m }: { m: MetricBlock }) {
  const rows: [string, string][] = [
    ["Sensitivity", fmtProportion(m.sensitivity)],
    ["Specificity", fmtProportion(m.specificity)],
    ["PPV", fmtProportion(m.ppv)],
    ["NPV", fmtProportion(m.npv)],
    ["Accuracy (prevalence-dependent)", fmtProportion(m.accuracy)],
    [
      "AUC",
      m.auc?.value == null
        ? `Not evaluated${m.auc?.reason ? ` (${m.auc.reason})` : ""}`
        : `${m.auc.value.toFixed(3)} (95% CI ${m.auc.ci_low?.toFixed(3) ?? "?"}–${m.auc.ci_high?.toFixed(3) ?? "?"}, ${m.auc.method})`,
    ],
    ["Failed-recording rate", fmtProportion(m.failed_recording_rate)],
  ];
  return (
    <table className="table">
      <tbody>
        {rows.map(([k, v]) => (
          <tr key={k}>
            <th className="w-56 normal-case tracking-normal">{k}</th>
            <td className="font-mono text-xs sm:text-sm">{v}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function EvaluationDetail() {
  const { id } = useParams();
  const { data: r, error, loading } = useApi<EvaluationRun>(`/research/evaluations/${id}`);
  if (loading && !r) return <Loading />;
  if (error) return <ErrorBox message={error} />;
  if (!r?.metrics) return null;
  const o = r.metrics.overall;
  const cm = o.confusion;
  return (
    <>
      <PageHeader
        title={`Evaluation #${r.id}`}
        subtitle={`${r.model.name} v${r.model.version} on ${r.dataset.name} · ${r.is_external ? "external validation" : "internal held-out test"} · threshold ${r.threshold} · ${fmtDate(r.created_at)}`}
        actions={
          <Link to="/research" className="btn-ghost">
            Back to lab
          </Link>
        }
      />
      {r.warnings.map((w) => (
        <div key={w} className="mb-2">
          <Notice tone="exp">{w}</Notice>
        </div>
      ))}
      <div className="mt-4 grid gap-6 lg:grid-cols-2">
        <section className="card">
          <div className="card-h">
            <h2 className="h-title">Overall performance</h2>
            <span className="text-xs text-slate-500">
              {o.n_recordings} recordings · {o.n_patients} patients · prevalence {o.prevalence != null ? (o.prevalence * 100).toFixed(1) + "%" : "—"}
            </span>
          </div>
          <div className="overflow-x-auto px-2 py-2">
            <MetricTable m={o} />
          </div>
        </section>
        <section className="card">
          <div className="card-h">
            <h2 className="h-title">Confusion matrix</h2>
          </div>
          <div className="card-b">
            {cm ? (
              <table className="table max-w-sm text-center" aria-label="Confusion matrix">
                <thead>
                  <tr>
                    <th />
                    <th className="text-center">Predicted +</th>
                    <th className="text-center">Predicted −</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <th>Actual +</th>
                    <td className="font-mono text-lg">{cm.tp}</td>
                    <td className="font-mono text-lg">{cm.fn}</td>
                  </tr>
                  <tr>
                    <th>Actual −</th>
                    <td className="font-mono text-lg">{cm.fp}</td>
                    <td className="font-mono text-lg">{cm.tn}</td>
                  </tr>
                </tbody>
              </table>
            ) : (
              <p className="text-sm text-slate-500">Not evaluated.</p>
            )}
          </div>
        </section>
        <section className="card">
          <div className="card-h">
            <h2 className="h-title">ROC curve</h2>
          </div>
          <div className="card-b h-72">
            {o.roc?.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={o.roc} margin={{ top: 8, right: 16, bottom: 20, left: 0 }}>
                  <CartesianGrid stroke={GRID} vertical={false} />
                  <XAxis dataKey="fpr" type="number" domain={[0, 1]} tick={AXIS} label={{ value: "1 − specificity", position: "insideBottom", offset: -10, ...AXIS }} />
                  <YAxis type="number" domain={[0, 1]} tick={AXIS} label={{ value: "Sensitivity", angle: -90, position: "insideLeft", ...AXIS }} />
                  <ReferenceLine segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]} stroke="#94a3b8" strokeDasharray="4 4" />
                  <Tooltip formatter={(v) => Number(v).toFixed(3)} labelFormatter={(l) => `FPR ${Number(l).toFixed(3)}`} />
                  <Line type="stepAfter" dataKey="tpr" name="Sensitivity" stroke={INK} strokeWidth={2} dot={false} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-sm text-slate-500">Not evaluated (requires both classes).</p>
            )}
          </div>
        </section>
        <section className="card">
          <div className="card-h">
            <h2 className="h-title">Calibration</h2>
            {o.calibration && (
              <span className="text-xs text-slate-500">
                ECE {o.calibration.ece} · Brier {o.calibration.brier} · slope {o.calibration.slope ?? "—"}
              </span>
            )}
          </div>
          <div className="card-b h-72">
            {o.calibration?.bins.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <ScatterChart margin={{ top: 8, right: 16, bottom: 20, left: 0 }}>
                  <CartesianGrid stroke={GRID} vertical={false} />
                  <XAxis dataKey="mean_predicted" type="number" domain={[0, 1]} tick={AXIS} name="Mean predicted" label={{ value: "Mean predicted score", position: "insideBottom", offset: -10, ...AXIS }} />
                  <YAxis dataKey="observed_rate" type="number" domain={[0, 1]} tick={AXIS} name="Observed rate" label={{ value: "Observed rate", angle: -90, position: "insideLeft", ...AXIS }} />
                  <ZAxis dataKey="n" range={[60, 240]} name="n" />
                  <ReferenceLine segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]} stroke="#94a3b8" strokeDasharray="4 4" />
                  <Tooltip cursor={false} />
                  <Scatter data={o.calibration.bins} fill={INK} stroke="#fff" strokeWidth={2} isAnimationActive={false} />
                </ScatterChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-sm text-slate-500">Not evaluated.</p>
            )}
          </div>
        </section>
      </div>

      <section className="card mt-6">
        <div className="card-h">
          <h2 className="h-title">Subgroups, devices and environments</h2>
        </div>
        <div className="card-b space-y-6">
          {Object.keys(r.metrics.subgroups).length === 0 && <p className="text-sm text-slate-500">No subgroup columns supplied — subgroup performance not evaluated.</p>}
          {Object.entries(r.metrics.subgroups).map(([col, groups]) => (
            <div key={col} className="overflow-x-auto">
              <h3 className="mb-2 text-sm font-semibold">{humanize(col)}</h3>
              <table className="table">
                <thead>
                  <tr>
                    <th>Group</th>
                    <th>n</th>
                    <th>Sensitivity</th>
                    <th>Specificity</th>
                    <th>AUC</th>
                    <th>Failed recordings</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(groups).map(([g, m]) => (
                    <tr key={g}>
                      <td>
                        {g}
                        {m.warning && <span className="block text-xs text-exp-800">{m.warning}</span>}
                      </td>
                      <td>{m.n_recordings}</td>
                      <td className="font-mono text-xs">{fmtProportion(m.sensitivity)}</td>
                      <td className="font-mono text-xs">{fmtProportion(m.specificity)}</td>
                      <td className="font-mono text-xs">{m.auc?.value != null ? m.auc.value.toFixed(3) : "Not evaluated"}</td>
                      <td className="font-mono text-xs">{fmtProportion(m.failed_recording_rate)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      </section>
    </>
  );
}
