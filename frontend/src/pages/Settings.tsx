import { useState } from "react";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { fmtDate } from "../lib/format";
import type { AuditEntry, User } from "../lib/types";
import { useApi } from "../lib/useApi";
import { Loading, Notice, PageHeader } from "../components/ui";

function AccessControl() {
  const { user, config } = useAuth();
  const sso = config?.mode === "oidc";
  const { data, setData } = useApi<User[]>("/admin/users");
  const [form, setForm] = useState({ email: "", full_name: "", role: "clinician", password: "" });
  const [err, setErr] = useState<string | null>(null);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    try {
      const u = await api.post<User>("/admin/users", sso ? { ...form, password: undefined } : form);
      setData([...(data ?? []), u]);
      setForm({ email: "", full_name: "", role: "clinician", password: "" });
      setErr(null);
    } catch (e) {
      setErr((e as Error).message);
    }
  }
  async function patch(u: User, body: Partial<User> & { unlock?: boolean }) {
    try {
      const nu = await api.patch<User>(`/admin/users/${u.id}`, body);
      setData((data ?? []).map((x) => (x.id === u.id ? nu : x)));
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  return (
    <section className="card">
      <div className="card-h">
        <h2 className="h-title">Access control</h2>
      </div>
      <div className="card-b space-y-4">
        <p className="text-sm text-slate-600">
          Clinicians: patient records, audio, reviews, reports. Researchers: datasets, models and evaluations — no patient audio. Admins: everything
          plus users, retention and audit.
        </p>
        <div className="overflow-x-auto">
          <table className="table">
            <thead>
              <tr>
                <th>User</th>
                <th>Role</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {data?.map((u) => (
                <tr key={u.id}>
                  <td>
                    {u.full_name}
                    <span className="block text-xs text-slate-500">
                      {u.email}
                      {u.sso_linked && " · SSO"}
                      {u.last_login_at && ` · last sign-in ${fmtDate(u.last_login_at)}`}
                    </span>
                    {u.locked_until && new Date(u.locked_until.endsWith("Z") ? u.locked_until : u.locked_until + "Z") > new Date() && (
                      <button className="mt-1 text-xs text-teal-700 underline" onClick={() => patch(u, { unlock: true })}>
                        Locked after failed sign-ins — unlock
                      </button>
                    )}
                  </td>
                  <td>
                    <select className="input" aria-label={`Role for ${u.email}`} value={u.role} disabled={u.id === user?.id} onChange={(e) => patch(u, { role: e.target.value as User["role"] })}>
                      <option value="clinician">Clinician</option>
                      <option value="researcher">Researcher</option>
                      <option value="admin">Admin</option>
                    </select>
                  </td>
                  <td>
                    <button className="btn-ghost px-3" disabled={u.id === user?.id} onClick={() => patch(u, { is_active: !u.is_active })}>
                      {u.is_active ? "Deactivate" : "Activate"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <form onSubmit={add} className="grid gap-3 sm:grid-cols-2">
          <input className="input" placeholder="Email" aria-label="New user email" type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          <input className="input" placeholder="Full name" aria-label="New user name" required value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
          <select className="input" aria-label="New user role" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
            <option value="clinician">Clinician</option>
            <option value="researcher">Researcher</option>
            <option value="admin">Admin</option>
          </select>
          {sso ? (
            <p className="self-center text-xs text-slate-500">Credentials and MFA are managed by your identity provider; the user links on first sign-in.</p>
          ) : (
            <input className="input" placeholder="Initial password (12+ chars)" aria-label="New user password" type="password" minLength={12} required value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
          )}
          {err && <p className="text-sm text-issue-700 sm:col-span-2">{err}</p>}
          <button className="btn-primary sm:col-span-2 sm:justify-self-start">Add user</button>
        </form>
      </div>
    </section>
  );
}

function Retention() {
  const { data, setData } = useApi<{ organization: string; retention_days: number }>("/admin/settings");
  const [days, setDays] = useState<string>("");
  const [msg, setMsg] = useState<string | null>(null);
  if (!data) return <Loading />;
  return (
    <section className="card">
      <div className="card-h">
        <h2 className="h-title">Privacy and data retention</h2>
      </div>
      <div className="card-b space-y-3 text-sm">
        <p>
          Audio for <b>{data.organization}</b> is retained for <b>{data.retention_days} days</b> after upload, then destroyed by the retention job. Audit
          records are kept.
        </p>
        <div className="flex flex-wrap items-end gap-2">
          <div>
            <label className="label" htmlFor="ret">
              Retention (days, 30–3650)
            </label>
            <input id="ret" className="input w-40" type="number" min={30} max={3650} value={days} placeholder={String(data.retention_days)} onChange={(e) => setDays(e.target.value)} />
          </div>
          <button className="btn-ghost" disabled={!days} onClick={async () => setData(await api.put("/admin/settings", { retention_days: Number(days) }))}>
            Save
          </button>
          <button
            className="btn-ghost"
            onClick={async () => {
              const r = await api.post<{ recordings_purged: number }>("/admin/retention/purge");
              setMsg(`${r.recordings_purged} expired recording(s) destroyed.`);
            }}
          >
            Run retention purge now
          </button>
        </div>
        {msg && <p className="text-teal-700">{msg}</p>}
      </div>
    </section>
  );
}

function AuditLog() {
  const { data, loading } = useApi<AuditEntry[]>("/admin/audit?limit=200");
  const [verify, setVerify] = useState<{ intact: boolean; first_bad_event_id: number | null } | null>(null);
  return (
    <section className="card">
      <div className="card-h">
        <h2 className="h-title">Audit log</h2>
        <button className="btn-ghost px-3" onClick={async () => setVerify(await api.get("/admin/audit/verify"))}>
          Verify integrity
        </button>
      </div>
      <div className="card-b space-y-3">
        {verify && (
          <Notice tone={verify.intact ? "info" : "issue"}>
            {verify.intact ? "Hash chain intact — no audit records have been altered." : `Hash chain broken at event #${verify.first_bad_event_id}. Investigate per incident procedure.`}
          </Notice>
        )}
        {loading && !data ? (
          <Loading />
        ) : (
          <div className="max-h-96 overflow-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Actor</th>
                  <th>Action</th>
                  <th className="hidden md:table-cell">Entity</th>
                </tr>
              </thead>
              <tbody>
                {data?.map((e) => (
                  <tr key={e.id}>
                    <td className="whitespace-nowrap text-xs">{fmtDate(e.ts)}</td>
                    <td className="text-xs">{e.actor ?? "system"}</td>
                    <td className="font-mono text-xs">{e.action}</td>
                    <td className="hidden text-xs md:table-cell">
                      {e.entity_type} {e.entity_id}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}

function SystemInfo() {
  const { data } = useApi<{ mode: { label: string; detail: string }; quality_pipeline: string; inference_contract: string; ffmpeg_available: boolean; api_version: string }>("/system/status");
  if (!data) return null;
  return (
    <section className="card">
      <div className="card-h">
        <h2 className="h-title">Integrations and system</h2>
      </div>
      <dl className="card-b grid grid-cols-1 gap-2 text-sm sm:grid-cols-2">
        <dt className="text-slate-500">Analysis mode</dt>
        <dd>{data.mode.label}</dd>
        <dt className="text-slate-500">Quality pipeline</dt>
        <dd className="font-mono">{data.quality_pipeline}</dd>
        <dt className="text-slate-500">Model inference contract</dt>
        <dd className="font-mono">{data.inference_contract}</dd>
        <dt className="text-slate-500">Non-WAV decoding (ffmpeg)</dt>
        <dd>{data.ffmpeg_available ? "Available" : "Not installed — WAV only"}</dd>
        <dt className="text-slate-500">API</dt>
        <dd className="font-mono">{data.api_version}</dd>
        <dt className="text-slate-500">EHR / FHIR integration</dt>
        <dd>Not configured</dd>
      </dl>
    </section>
  );
}

export default function Settings() {
  const { user, can } = useAuth();
  return (
    <>
      <PageHeader title="Settings" subtitle={`Signed in as ${user?.full_name} (${user?.role}).`} />
      <div className="space-y-6">
        <Notice title="Privacy notice">
          Heart-sound recordings and linked records are sensitive health data. They are encrypted in transit (deploy behind TLS) and at rest, accessible
          only to authorised clinical roles in your organisation, and every access is audited. Collect only what the intended use requires. Before any
          real-patient use, confirm applicable medical-device, clinical-governance and privacy obligations in your jurisdiction.
        </Notice>
        <SystemInfo />
        {can("admin") && (
          <>
            <AccessControl />
            <Retention />
            <AuditLog />
          </>
        )}
      </div>
    </>
  );
}
