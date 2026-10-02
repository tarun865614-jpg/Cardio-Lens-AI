import { Link } from "react-router-dom";
import { fmtDate, humanize } from "../lib/format";
import type { Dashboard as D, Recording } from "../lib/types";
import { useApi } from "../lib/useApi";
import { DemoBadge, Empty, ErrorBox, Icon, Loading, PageHeader, QualityBadge, ReviewBadge, TierBadge } from "../components/ui";

function Stat({ label, value, tone = "navy", to }: { label: string; value: number; tone?: "navy" | "issue" | "flag" | "teal"; to?: string }) {
  const color = { navy: "text-navy-900", issue: "text-issue-700", flag: "text-flag-700", teal: "text-teal-700" }[tone];
  const body = (
    <div className="card card-b h-full transition hover:border-teal-300">
      <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">{label}</p>
      <p className={`mt-1 text-2xl font-semibold ${color}`}>{value}</p>
    </div>
  );
  return to ? <Link to={to}>{body}</Link> : body;
}

export function RecordingRow({ r }: { r: Recording }) {
  return (
    <li>
      <Link to={`/recordings/${r.id}`} className="flex flex-col gap-1.5 rounded-lg px-2 py-2.5 hover:bg-slate-50">
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">
            {r.patient_pseudonym} · {humanize(r.auscultation_site)}
          </p>
          <p className="truncate text-xs text-slate-500">
            {fmtDate(r.recorded_at ?? r.created_at)} · {humanize(r.device_type)} · {r.duration_s?.toFixed(1)} s
          </p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {r.is_demo && <DemoBadge />}
          <QualityBadge status={r.quality_status} />
          <TierBadge tier={r.latest_result_tier} status={r.latest_model_status} />
          <ReviewBadge status={r.review_status} />
        </div>
      </Link>
    </li>
  );
}

function ListCard({ title, items, empty, icon }: { title: string; items: Recording[]; empty: string; icon: string }) {
  return (
    <section className="card">
      <div className="card-h">
        <h2 className="h-title flex items-center gap-2">
          <Icon name={icon} /> {title}
        </h2>
      </div>
      <div className="px-2 py-2 sm:px-3">
        {items.length ? <ul className="divide-y divide-slate-100">{items.map((r) => <RecordingRow key={r.id} r={r} />)}</ul> : <p className="p-3 text-sm text-slate-500">{empty}</p>}
      </div>
    </section>
  );
}

export default function Dashboard() {
  const { data, error, loading } = useApi<D>("/dashboard");
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox message={error} />;
  if (!data) return null;
  const c = data.counts;
  return (
    <>
      <PageHeader
        title="Dashboard"
        subtitle="Recordings awaiting review, technical quality issues and system status."
        actions={
          <Link to="/record" className="btn-teal">
            <Icon name="mic" /> New recording
          </Link>
        }
      />
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="Patients" value={c.patients} to="/patients" />
        <Stat label="Recordings" value={c.recordings} />
        <Stat label="Pending review" value={c.pending_review} tone="teal" />
        <Stat label="Flagged follow-up" value={c.flagged} tone="flag" />
        <Stat label="Unusable audio" value={c.quality_unusable} tone="issue" />
        <Stat label="Quality warnings" value={c.quality_warnings} tone="issue" />
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <ListCard title="Pending reviews" icon="check" items={data.pending_reviews} empty="Nothing waiting for review." />
        <ListCard title="Flagged for clinical follow-up" icon="flag" items={data.flagged} empty="No flagged cases." />
        <ListCard title="Recording quality issues (technical)" icon="wrench" items={data.quality_issues} empty="No unusable recordings." />
        <section className="card">
          <div className="card-h">
            <h2 className="h-title">System status</h2>
          </div>
          <div className="card-b space-y-2 text-sm">
            <p>
              <span className="font-medium">Analysis mode:</span> {data.system.label}
            </p>
            <p className="text-slate-600">{data.system.detail}</p>
            {data.system.model ? (
              <p className="text-slate-600">
                Model {data.system.model.name} v{data.system.model.version} — {humanize(data.system.model.validation_status)}
                {data.system.model.calibrated ? ", calibrated" : ", uncalibrated"}
              </p>
            ) : (
              <p className="text-slate-600">No screening model is active. This is intentional until a model passes independent validation.</p>
            )}
          </div>
        </section>
      </div>

      <div className="mt-6">
        {data.recent.length ? (
          <ListCard title="Recent recordings" icon="mic" items={data.recent} empty="" />
        ) : (
          <Empty title="No recordings yet">Start with a new recording.</Empty>
        )}
      </div>
    </>
  );
}
