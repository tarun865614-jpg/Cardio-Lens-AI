import { useState } from "react";
import { Navigate } from "react-router-dom";
import { homeFor, useAuth } from "../lib/auth";

const DEMO = import.meta.env.DEV || import.meta.env.VITE_SHOW_DEMO_ACCOUNTS === "true";

export default function Login() {
  const { user, login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to={homeFor(user.role)} replace />;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await login(email, password);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-full items-center justify-center bg-navy-900 px-4 py-10">
      <div className="w-full max-w-md">
        <div className="mb-6 text-center text-white">
          <svg viewBox="0 0 32 32" className="mx-auto h-12 w-12" aria-hidden="true">
            <rect width="32" height="32" rx="7" fill="#13294b" />
            <path d="M4 17h6l2-6 4 12 3-9 2 3h7" fill="none" stroke="#5eead4" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <h1 className="mt-3 text-2xl font-semibold">CardioLens AI</h1>
          <p className="mt-1 text-sm text-teal-100">Heart-sound capture, quality analysis and clinician review</p>
        </div>
        <form onSubmit={submit} className="card card-b space-y-4">
          <div>
            <label htmlFor="email" className="label">
              Email
            </label>
            <input id="email" type="email" autoComplete="username" required className="input" value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div>
            <label htmlFor="password" className="label">
              Password
            </label>
            <input id="password" type="password" autoComplete="current-password" required className="input" value={password} onChange={(e) => setPassword(e.target.value)} />
          </div>
          {err && (
            <p role="alert" className="text-sm text-issue-700">
              {err}
            </p>
          )}
          <button className="btn-primary w-full" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
          <p className="text-xs text-slate-500">
            Research prototype. Not a medical device and not cleared for diagnostic use. Access is logged.
          </p>
        </form>
        {DEMO && (
          <div className="mt-4 rounded-lg bg-navy-800 p-4 text-xs text-slate-200">
            <p className="mb-2 font-semibold text-white">Development demo accounts (synthetic data only)</p>
            {["clinician", "researcher", "admin"].map((r) => (
              <button
                key={r}
                type="button"
                className="mr-2 mt-1 rounded bg-navy-700 px-2 py-1 hover:bg-navy-600"
                onClick={() => {
                  setEmail(`${r}@demo.cardiolens.local`);
                  setPassword("demo-password-123");
                }}
              >
                {r}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
