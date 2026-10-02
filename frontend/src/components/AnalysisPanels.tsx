import { useState } from "react";
import { api } from "../lib/api";
import { fmtDate, fmtScore, humanize } from "../lib/format";
import type { Analysis, QualityReport, Review, ReviewStatus } from "../lib/types";
import { CheckBadge, Icon, Notice, QualityBadge, ReviewBadge, TierBadge } from "./ui";

export function QualityPanel({ q }: { q: QualityReport }) {
  return (
    <section className="card" aria-labelledby="q-title">
      <div className="card-h">
        <h2 id="q-title" className="h-title">
          Recording quality <span className="font-normal text-slate-500">({q.pipeline_version})</span>
        </h2>
        <QualityBadge status={q.overall} />
      </div>
      <div className="card-b space-y-3">
        {q.overall === "unusable" ? (
          <Notice tone="issue" title="Technical recording problem — please record again">
            {q.headline} This is a recording-quality issue, not a clinical finding. No AI analysis was run.
          </Notice>
        ) : (
          <p className="text-sm text-slate-700">{q.headline}</p>
        )}
        <ul className="divide-y divide-slate-100">
          {q.checks.map((c) => (
            <li key={c.id} className="flex flex-col gap-1 py-2 sm:flex-row sm:items-start sm:gap-3">
              <div className="flex items-center gap-2 sm:w-64 sm:shrink-0">
                <CheckBadge status={c.status} />
                <span className="text-sm font-medium">{c.label}</span>
              </div>
              <div className="flex-1 text-sm text-slate-600">
                {c.explanation}
                <span className="mt-0.5 block text-xs text-slate-500">
                  measured: {String(c.value)} · target: {c.threshold}
                </span>
              </div>
            </li>
          ))}
        </ul>
        {q.notes.map((n) => (
          <p key={n} className="text-xs text-slate-500">
            {n}
          </p>
        ))}
        <p className="text-xs text-slate-500">{q.disclaimer}</p>
      </div>
    </section>
  );
}

export function ModelPanel({ a }: { a: Analysis }) {
  const mo = a.model_output;
  return (
    <section className="card" aria-labelledby="m-title" data-testid="model-panel">
      <div className="card-h">
        <h2 id="m-title" className="h-title">
          AI analysis
        </h2>
        <TierBadge tier={a.result_tier} status={a.model_status} />
      </div>
      <div className="card-b space-y-3 text-sm">
        {a.model_status === "no_model" && (
          <Notice title="Research-demo mode">
            {a.model_status_text} Signal-quality measurements and visualisations above are the only automated outputs. No disease
            prediction has been simulated.
          </Notice>
        )}
        {a.model_status === "not_run_quality" && <Notice tone="issue">{a.model_status_text}</Notice>}
        {a.model_status === "service_error" && (
          <Notice tone="issue" title="Model service unavailable">
            {a.error ?? a.model_status_text} Nothing has been inferred for this recording. You may retry analysis later.
          </Notice>
        )}
        {a.model_status === "completed" && mo && (
          <>
            {a.result_tier === "experimental" && (
              <Notice tone="exp" title="Experimental output — research use only">
                {mo.tier_reason} Do not use for clinical decisions.
              </Notice>
            )}
            {a.result_tier === "validated" && (
              <Notice title="Screening output from a validated model">
                {mo.tier_reason} This is a screening aid, not a diagnosis. A low score does not mean the heart is healthy.
              </Notice>
            )}
            {mo.abstained ? (
              <p className="text-slate-700">Model abstained: {mo.abstain_reason}</p>
            ) : (
              <div>
                <p className="label">What the model was trained to detect — scores</p>
                <ul className="space-y-2">
                  {mo.scores.map((s) => (
                    <li key={s.category}>
                      <div className="flex items-baseline justify-between gap-3">
                        <span>{s.label}</span>
                        <span className="font-mono">{fmtScore(s.score)}</span>
                      </div>
                      <div className="mt-1 h-1.5 rounded bg-slate-100">
                        <div className="h-1.5 rounded bg-navy-700" style={{ width: `${s.score * 100}%` }} />
                      </div>
                      <p className="mt-0.5 text-xs text-slate-500">
                        {s.score_type === "calibrated_probability" ? "Calibrated probability (per model card)" : "Uncalibrated model score — not a probability of disease"}
                      </p>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {mo.model_card && (
              <dl className="grid grid-cols-1 gap-x-4 gap-y-1 rounded-lg bg-slate-50 p-3 text-xs sm:grid-cols-2">
                <dt className="text-slate-500">Model</dt>
                <dd>
                  {mo.model_card.name} v{mo.model_card.version}
                </dd>
                <dt className="text-slate-500">Validation status</dt>
                <dd>{humanize(mo.model_card.validation_status)}</dd>
                <dt className="text-slate-500">Intended use</dt>
                <dd>{mo.model_card.intended_use}</dd>
                <dt className="text-slate-500">Analysed</dt>
                <dd>{fmtDate(a.created_at)}</dd>
              </dl>
            )}
            {!!mo.limitations?.length && (
              <div>
                <p className="label">Limitations</p>
                <ul className="list-disc space-y-1 pl-5 text-slate-600">
                  {mo.limitations.map((l) => (
                    <li key={l}>{l}</li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
        <ul className="space-y-1 border-t border-slate-100 pt-3 text-xs text-slate-500">
          {a.boundaries.map((b) => (
            <li key={b} className="flex gap-2">
              <Icon name="info" className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              {b}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

export function ReviewPanel({ recordingId, reviews, onSaved }: { recordingId: number; reviews: Review[]; onSaved: () => void }) {
  const [status, setStatus] = useState<ReviewStatus>("reviewed");
  const [note, setNote] = useState("");
  const [conclusion, setConclusion] = useState("");
  const [flag, setFlag] = useState(false);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setErr(null);
    try {
      await api.post(`/recordings/${recordingId}/reviews`, {
        status,
        note,
        clinician_conclusion: conclusion || null,
        flagged_for_followup: flag,
      });
      setNote("");
      setConclusion("");
      setFlag(false);
      onSaved();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="card" aria-labelledby="r-title">
      <div className="card-h">
        <h2 id="r-title" className="h-title">
          Clinician review
        </h2>
      </div>
      <div className="card-b space-y-4">
        <form onSubmit={submit} className="space-y-3">
          <div>
            <label className="label" htmlFor="rv-status">
              Review status
            </label>
            <select id="rv-status" className="input" value={status} onChange={(e) => setStatus(e.target.value as ReviewStatus)}>
              <option value="in_review">In review</option>
              <option value="reviewed">Reviewed</option>
            </select>
          </div>
          <div>
            <label className="label" htmlFor="rv-note">
              Notes
            </label>
            <textarea id="rv-note" className="input min-h-20" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Listening findings, context, quality concerns…" />
          </div>
          <div>
            <label className="label" htmlFor="rv-concl">
              Clinician conclusion / next steps
            </label>
            <textarea id="rv-concl" className="input min-h-16" value={conclusion} onChange={(e) => setConclusion(e.target.value)} placeholder="Entered by you — shown separately from automated output in reports" />
          </div>
          <label className="flex items-start gap-2 text-sm">
            <input type="checkbox" className="mt-1 h-4 w-4 accent-flag-700" checked={flag} onChange={(e) => setFlag(e.target.checked)} />
            <span>Flag this case for further clinical evaluation</span>
          </label>
          {err && <p className="text-sm text-issue-700">{err}</p>}
          <button className="btn-primary w-full sm:w-auto" disabled={saving}>
            {saving ? "Saving…" : "Save review"}
          </button>
        </form>
        <div>
          <p className="label">History</p>
          {reviews.length === 0 ? (
            <p className="text-sm text-slate-500">No reviews yet.</p>
          ) : (
            <ol className="space-y-3">
              {[...reviews].reverse().map((r) => (
                <li key={r.id} className="border-l-2 border-teal-500 pl-3 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{r.reviewer?.full_name}</span>
                    <span className="text-xs text-slate-500">{fmtDate(r.created_at)}</span>
                    <ReviewBadge status={r.status} />
                  </div>
                  {r.note && <p className="mt-1 whitespace-pre-wrap text-slate-700">{r.note}</p>}
                  {r.clinician_conclusion && (
                    <p className="mt-1 text-slate-700">
                      <span className="font-medium">Conclusion:</span> {r.clinician_conclusion}
                    </p>
                  )}
                </li>
              ))}
            </ol>
          )}
        </div>
      </div>
    </section>
  );
}
