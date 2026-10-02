import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { ADMIN, CLINICAL, RESEARCH, useAuth } from "../lib/auth";
import type { Role } from "../lib/types";
import { useApi } from "../lib/useApi";
import type { SystemMode } from "../lib/types";
import { Icon } from "./ui";

const NAV: { to: string; label: string; icon: string; roles: Role[] }[] = [
  { to: "/", label: "Dashboard", icon: "dashboard", roles: CLINICAL },
  { to: "/record", label: "New Recording", icon: "mic", roles: CLINICAL },
  { to: "/patients", label: "Patient Records", icon: "users", roles: CLINICAL },
  { to: "/reports", label: "Reports", icon: "report", roles: CLINICAL },
  { to: "/research", label: "Research Lab", icon: "flask", roles: RESEARCH },
  { to: "/settings", label: "Settings", icon: "settings", roles: [...CLINICAL, ...RESEARCH, ...ADMIN] },
];

export function ModeBanner({ mode }: { mode: SystemMode | null }) {
  if (!mode) return null;
  const tone =
    mode.mode === "validated_model"
      ? "bg-teal-700 text-white"
      : mode.mode === "experimental_model"
        ? "bg-exp-50 text-exp-800 border-b border-exp-300"
        : mode.mode === "model_error"
          ? "bg-issue-50 text-issue-700 border-b border-issue-200"
          : "bg-navy-800 text-teal-100";
  return (
    <div className={`px-4 py-2 text-xs sm:text-sm ${tone}`} role="note" data-testid="mode-banner">
      <span className="font-semibold">{mode.label}.</span> <span className="opacity-90">{mode.detail}</span>{" "}
      <span className="opacity-90">Not a diagnostic device — findings must be reviewed by a qualified professional.</span>
    </div>
  );
}

export default function Layout() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const { data: status } = useApi<{ mode: SystemMode }>("/system/status");
  const items = NAV.filter((n) => user && n.roles.includes(user.role));

  return (
    <div className="flex min-h-full flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:bg-white focus:p-2">
        Skip to content
      </a>
      <ModeBanner mode={status?.mode ?? null} />
      <div className="flex flex-1">
        <aside
          className={`fixed inset-y-0 left-0 z-40 w-64 transform bg-navy-900 text-slate-200 transition lg:static lg:translate-x-0 ${open ? "translate-x-0" : "-translate-x-full"}`}
          aria-label="Primary"
        >
          <div className="flex h-16 items-center gap-2 px-5">
            <svg viewBox="0 0 32 32" className="h-8 w-8" aria-hidden="true">
              <rect width="32" height="32" rx="7" fill="#13294b" />
              <path d="M4 17h6l2-6 4 12 3-9 2 3h7" fill="none" stroke="#5eead4" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <div>
              <p className="text-sm font-semibold text-white">CardioLens AI</p>
              <p className="text-[11px] uppercase tracking-widest text-teal-300">Research platform</p>
            </div>
          </div>
          <nav className="mt-2 space-y-1 px-3">
            {items.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.to === "/"}
                onClick={() => setOpen(false)}
                className={({ isActive }) =>
                  `flex min-h-10 items-center gap-3 rounded-lg px-3 py-2 text-sm ${isActive ? "bg-navy-700 text-white" : "text-slate-300 hover:bg-navy-800 hover:text-white"}`
                }
              >
                <Icon name={n.icon} />
                {n.label}
              </NavLink>
            ))}
          </nav>
          <div className="absolute inset-x-0 bottom-0 border-t border-navy-700 p-4 text-xs">
            <p className="truncate font-medium text-white">{user?.full_name}</p>
            <p className="truncate text-slate-300">
              {user?.email} · <span className="capitalize">{user?.role}</span>
            </p>
            <button onClick={logout} className="mt-3 inline-flex items-center gap-2 text-slate-300 hover:text-white">
              <Icon name="logout" /> Sign out
            </button>
          </div>
        </aside>
        {open && <div className="fixed inset-0 z-30 bg-navy-950/40 lg:hidden" onClick={() => setOpen(false)} aria-hidden="true" />}

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex h-14 items-center gap-3 border-b border-slate-200 bg-white px-4 lg:hidden">
            <button className="btn-ghost px-2" onClick={() => setOpen(true)} aria-label="Open navigation">
              <Icon name="menu" className="h-5 w-5" />
            </button>
            <span className="text-sm font-semibold">CardioLens AI</span>
          </header>
          <main id="main" className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6 lg:px-8">
            <Outlet />
          </main>
        </div>
      </div>
    </div>
  );
}
