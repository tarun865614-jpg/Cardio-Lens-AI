import { useState } from "react";
import { Link } from "react-router-dom";
import { api, downloadFile } from "../lib/api";
import { fmtDate, humanize } from "../lib/format";
import type { Recording } from "../lib/types";
import { useApi } from "../lib/useApi";
import { DemoBadge, Empty, ErrorBox, Loading, PageHeader, QualityBadge, ReviewBadge, TierBadge } from "../components/ui";

export default function Reports() {
  const [review, setReview] = useState("");
  const { data, error, loading } = useApi<Recording[]>(`/recordings${review ? `?review_status=${review}` : ""}`);

  async function exportJson(r: Recording) {
    const rep = await api.get<unknown>(`/recordings/${r.id}/report`);
    const blob = new Blob([JSON.stringify(rep, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `cardiolens-report-${r.patient_pseudonym}-${r.id}.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return (
    <>
      <PageHeader
        title="Reports"
        subtitle="Exports keep three sections apart: automated signal quality, automated model output (with its tier), and clinician-entered conclusions."
      />
      <div className="mb-4 max-w-xs">
        <label className="label" htmlFor="rf">
          Review status
        </label>
        <select id="rf" className="input" value={review} onChange={(e) => setReview(e.target.value)}>
          <option value="">All</option>
          <option value="pending">Pending</option>
          <option value="in_review">In review</option>
          <option value="reviewed">Reviewed</option>
          <option value="flagged">Flagged</option>
        </select>
      </div>
      {error && <ErrorBox message={error} />}
      {loading && !data ? (
        <Loading />
      ) : data?.length ? (
        <div className="card overflow-x-auto">
          <table className="table">
            <thead>
              <tr>
                <th>Recording</th>
                <th className="hidden md:table-cell">Status</th>
                <th>Export</th>
              </tr>
            </thead>
            <tbody>
              {data.map((r) => (
                <tr key={r.id}>
                  <td>
                    <Link to={`/recordings/${r.id}`} className="font-medium text-navy-800 underline-offset-2 hover:underline">
                      {r.patient_pseudonym} · {humanize(r.auscultation_site)}
                    </Link>
                    <span className="block text-xs text-slate-500">{fmtDate(r.recorded_at ?? r.created_at)}</span>
                  </td>
                  <td className="hidden md:table-cell">
                    <div className="flex flex-wrap gap-1">
                      {r.is_demo && <DemoBadge />}
                      <QualityBadge status={r.quality_status} />
                      <TierBadge tier={r.latest_result_tier} status={r.latest_model_status} />
                      <ReviewBadge status={r.review_status} />
                    </div>
                  </td>
                  <td>
                    <div className="flex flex-wrap gap-2">
                      <button className="btn-ghost px-3" onClick={() => downloadFile(`/recordings/${r.id}/report?format=html`, `cardiolens-report-${r.patient_pseudonym}-${r.id}.html`)}>
                        HTML
                      </button>
                      <button className="btn-ghost px-3" onClick={() => exportJson(r)}>
                        JSON
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <Empty title="No recordings match" />
      )}
    </>
  );
}
