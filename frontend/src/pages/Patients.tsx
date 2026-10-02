import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { fmtDate } from "../lib/format";
import type { Patient } from "../lib/types";
import { useApi } from "../lib/useApi";
import { RecordingRow } from "./Dashboard";
import { DemoBadge, Empty, ErrorBox, Icon, Loading, PageHeader, QualityBadge } from "../components/ui";

export function PatientList() {
  const [q, setQ] = useState("");
  const [openOnly, setOpenOnly] = useState(false);
  const path = `/patients?${new URLSearchParams({ ...(q ? { q } : {}), ...(openOnly ? { has_open_reviews: "true" } : {}) })}`;
  const { data, error, loading, setData } = useApi<Patient[]>(path);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ external_ref: "", birth_year: "", sex: "" });

  async function create(e: React.FormEvent) {
    e.preventDefault();
    const body: Record<string, unknown> = {};
    if (form.external_ref) body.external_ref = form.external_ref;
    if (form.birth_year) body.birth_year = Number(form.birth_year);
    if (form.sex) body.sex = form.sex;
    const p = await api.post<Patient>("/patients", body);
    setData([p, ...(data ?? [])]);
    setCreating(false);
    setForm({ external_ref: "", birth_year: "", sex: "" });
  }

  return (
    <>
      <PageHeader
        title="Patient records"
        subtitle="Patients are identified by generated pseudonyms. Store a site reference only if linkage is required."
        actions={
          <button className="btn-teal" onClick={() => setCreating((v) => !v)}>
            New patient
          </button>
        }
      />
      {creating && (
        <form onSubmit={create} className="card card-b mb-4 grid gap-3 sm:grid-cols-4 sm:items-end">
          <div>
            <label className="label" htmlFor="ext">
              Site reference (optional)
            </label>
            <input id="ext" className="input" maxLength={64} value={form.external_ref} onChange={(e) => setForm({ ...form, external_ref: e.target.value })} />
          </div>
          <div>
            <label className="label" htmlFor="by">
              Birth year (optional)
            </label>
            <input id="by" className="input" type="number" min={1900} max={2100} value={form.birth_year} onChange={(e) => setForm({ ...form, birth_year: e.target.value })} />
          </div>
          <div>
            <label className="label" htmlFor="sex">
              Sex (optional)
            </label>
            <select id="sex" className="input" value={form.sex} onChange={(e) => setForm({ ...form, sex: e.target.value })}>
              <option value="">—</option>
              <option value="female">Female</option>
              <option value="male">Male</option>
              <option value="other">Other</option>
              <option value="unknown">Unknown</option>
            </select>
          </div>
          <button className="btn-primary">Create</button>
        </form>
      )}
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center">
        <input className="input sm:max-w-xs" placeholder="Search pseudonym or reference…" aria-label="Search patients" value={q} onChange={(e) => setQ(e.target.value)} />
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={openOnly} onChange={(e) => setOpenOnly(e.target.checked)} /> Only with open reviews
        </label>
      </div>
      {error && <ErrorBox message={error} />}
      {loading && !data ? (
        <Loading />
      ) : data && data.length ? (
        <div className="card overflow-x-auto">
          <table className="table">
            <thead>
              <tr>
                <th>Patient</th>
                <th className="hidden sm:table-cell">Birth year</th>
                <th>Recordings</th>
                <th className="hidden md:table-cell">Last recording</th>
                <th>Open reviews</th>
              </tr>
            </thead>
            <tbody>
              {data.map((p) => (
                <tr key={p.id} className="hover:bg-slate-50">
                  <td>
                    <Link to={`/patients/${p.id}`} className="font-medium text-navy-800 underline-offset-2 hover:underline">
                      {p.pseudonym}
                    </Link>
                    {p.external_ref && <span className="ml-2 text-xs text-slate-500">{p.external_ref}</span>}
                    {p.is_synthetic && (
                      <span className="ml-2">
                        <DemoBadge />
                      </span>
                    )}
                  </td>
                  <td className="hidden sm:table-cell">{p.birth_year ?? "—"}</td>
                  <td>{p.recording_count}</td>
                  <td className="hidden md:table-cell">{fmtDate(p.last_recording_at)}</td>
                  <td>{p.open_reviews}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <Empty title="No patients found" />
      )}
    </>
  );
}

export function PatientDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const { can } = useAuth();
  const { data: p, error, loading } = useApi<Patient>(`/patients/${id}`);
  if (loading && !p) return <Loading />;
  if (error) return <ErrorBox message={error} />;
  if (!p) return null;
  const recs = p.recordings ?? [];
  const live = recs.filter((r) => r.audio_available);

  async function erase() {
    if (!confirm(`Erase patient ${p!.pseudonym}? All audio will be destroyed. The audit trail is retained.`)) return;
    await api.del(`/patients/${p!.id}`);
    nav("/patients");
  }

  return (
    <>
      <PageHeader
        title={`Patient ${p.pseudonym}`}
        subtitle={
          <>
            {p.external_ref && <>Ref {p.external_ref} · </>}
            {p.birth_year ? `Born ${p.birth_year}` : "Birth year not recorded"} · {p.sex ?? "sex not recorded"} · created {fmtDate(p.created_at, false)}
          </>
        }
        actions={
          <>
            <Link to={`/record?patient=${p.id}`} className="btn-teal">
              <Icon name="mic" /> New recording
            </Link>
            {can("admin") && (
              <button className="btn-danger" onClick={erase}>
                Erase patient
              </button>
            )}
          </>
        }
      />
      {p.is_synthetic && (
        <div className="mb-4">
          <DemoBadge />
        </div>
      )}
      <div className="grid gap-6 lg:grid-cols-3">
        <section className="card lg:col-span-2">
          <div className="card-h">
            <h2 className="h-title">Recordings</h2>
          </div>
          <div className="px-2 py-2 sm:px-3">
            {live.length ? (
              <ul className="divide-y divide-slate-100">
                {live.map((r) => (
                  <RecordingRow key={r.id} r={r} />
                ))}
              </ul>
            ) : (
              <p className="p-3 text-sm text-slate-500">No recordings.</p>
            )}
          </div>
        </section>
        <section className="card">
          <div className="card-h">
            <h2 className="h-title">Quality history</h2>
          </div>
          <div className="card-b">
            {recs.length ? (
              <ol className="space-y-2">
                {recs.map((r) => (
                  <li key={r.id} className="flex items-center justify-between gap-2 text-sm">
                    <span className="text-slate-600">{fmtDate(r.recorded_at ?? r.created_at, false)}</span>
                    {r.deleted_at ? <span className="badge bg-slate-100 text-slate-500">Deleted</span> : <QualityBadge status={r.quality_status} />}
                  </li>
                ))}
              </ol>
            ) : (
              <p className="text-sm text-slate-500">No history yet.</p>
            )}
          </div>
        </section>
      </div>
    </>
  );
}
