import type { ReactNode } from "react";
import type { CheckStatus, ModelStatus, QualityOverall, ResultTier, ReviewStatus } from "../lib/types";

export function Icon({ name, className = "h-4 w-4" }: { name: string; className?: string }) {
  const paths: Record<string, ReactNode> = {
    dashboard: <path d="M3 13h8V3H3zm10 8h8V11h-8zM3 21h8v-6H3zm10-18v6h8V3z" />,
    mic: <path d="M12 14a3 3 0 0 0 3-3V5a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.9V21h2v-3.1A7 7 0 0 0 19 11z" />,
    users: <path d="M16 11a3 3 0 1 0-3-3 3 3 0 0 0 3 3zm-8 0a3 3 0 1 0-3-3 3 3 0 0 0 3 3zm0 2c-2.3 0-7 1.2-7 3.5V19h14v-2.5C15 14.2 10.3 13 8 13zm8 0h-1a4.2 4.2 0 0 1 2 3.5V19h6v-2.5c0-2.3-4.7-3.5-7-3.5z" />,
    flask: <path d="M9 2v2h1v5.3L4.6 18.5A2.3 2.3 0 0 0 6.6 22h10.8a2.3 2.3 0 0 0 2-3.5L14 9.3V4h1V2zm3 2v5.9L14.7 14H9.3L12 9.9z" />,
    report: <path d="M6 2h9l5 5v15H6zm8 1.5V8h4.5M8 12h8v1.5H8zm0 3h8v1.5H8zm0 3h5v1.5H8z" />,
    settings: <path d="M19.4 13a7.6 7.6 0 0 0 0-2l2.1-1.6-2-3.5-2.5 1a7.4 7.4 0 0 0-1.7-1L15 3h-4l-.4 2.9a7.4 7.4 0 0 0-1.7 1l-2.5-1-2 3.5L6.6 11a7.6 7.6 0 0 0 0 2l-2.1 1.6 2 3.5 2.5-1a7.4 7.4 0 0 0 1.7 1L11 21h4l.4-2.9a7.4 7.4 0 0 0 1.7-1l2.5 1 2-3.5zM13 15.5a3.5 3.5 0 1 1 3.5-3.5 3.5 3.5 0 0 1-3.5 3.5z" />,
    wrench: <path d="M22 19.6 13.4 11a5.5 5.5 0 0 0-7-7l3.3 3.3-2.4 2.4L4 6.4a5.5 5.5 0 0 0 7 7l8.6 8.6z" />,
    flag: <path d="M5 21V4h9l.5 2H20v9h-6l-.5-2H7v8z" />,
    check: <path d="m9 16.2-4.2-4.2-1.4 1.4L9 19 21 7l-1.4-1.4z" />,
    info: <path d="M11 7h2v2h-2zm0 4h2v6h-2zm1-9a10 10 0 1 0 10 10A10 10 0 0 0 12 2z" />,
    beaker: <path d="M7 2h10v2h-1v4l5 11a2 2 0 0 1-1.8 3H4.8A2 2 0 0 1 3 19L8 8V4H7z" />,
    menu: <path d="M3 6h18v2H3zm0 5h18v2H3zm0 5h18v2H3z" />,
    logout: <path d="M10 17v-3H3v-4h7V7l5 5zm2-15h8a2 2 0 0 1 2 2v16a2 2 0 0 1-2 2h-8v-2h8V4h-8z" />,
  };
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" className={className}>
      {paths[name]}
    </svg>
  );
}

export function QualityBadge({ status }: { status: QualityOverall | null }) {
  if (!status) return <span className="badge bg-slate-100 text-slate-600">Not analysed</span>;
  const map = {
    usable: ["bg-teal-50 text-teal-700 ring-1 ring-teal-100", "Quality: usable"],
    usable_with_warnings: ["bg-issue-50 text-issue-700 ring-1 ring-issue-200", "Quality: warnings"],
    unusable: ["bg-issue-50 text-issue-700 ring-1 ring-issue-200", "Recording issue"],
  } as const;
  const [cls, text] = map[status];
  return (
    <span className={`badge ${cls}`} title="Technical recording quality — not a clinical finding">
      {status === "unusable" && <Icon name="wrench" className="h-3 w-3" />}
      {text}
    </span>
  );
}

export function CheckBadge({ status }: { status: CheckStatus }) {
  const cls = { pass: "bg-teal-50 text-teal-700", warn: "bg-issue-50 text-issue-700", fail: "bg-issue-50 text-issue-700 font-semibold" }[status];
  const text = { pass: "Pass", warn: "Warning", fail: "Fail" }[status];
  return <span className={`badge ${cls}`}>{text}</span>;
}

export function TierBadge({ tier, status }: { tier: ResultTier | null; status?: ModelStatus | null }) {
  if (status === "service_error") return <span className="badge bg-slate-100 text-slate-700">Model unavailable</span>;
  if (status === "not_run_quality") return <span className="badge bg-slate-100 text-slate-600">Not analysed (quality)</span>;
  if (!tier) return <span className="badge bg-slate-100 text-slate-600">—</span>;
  const map = {
    signal_only: ["bg-navy-900/5 text-navy-800", "Signal analysis only"],
    experimental: ["bg-exp-50 text-exp-800 ring-1 ring-exp-300", "Experimental AI"],
    validated: ["bg-teal-600 text-white", "Validated model"],
  } as const;
  const [cls, text] = map[tier];
  return <span className={`badge ${cls}`}>{text}</span>;
}

export function ReviewBadge({ status }: { status: ReviewStatus }) {
  const map = {
    pending: ["bg-slate-100 text-slate-700", "Pending review"],
    in_review: ["bg-navy-900/5 text-navy-800", "In review"],
    reviewed: ["bg-teal-50 text-teal-700", "Reviewed"],
    flagged: ["bg-flag-50 text-flag-700 ring-1 ring-flag-200", "Flagged for follow-up"],
  } as const;
  const [cls, text] = map[status];
  return (
    <span className={`badge ${cls}`}>
      {status === "flagged" && <Icon name="flag" className="h-3 w-3" />}
      {text}
    </span>
  );
}

export function DemoBadge() {
  return <span className="badge bg-exp-50 text-exp-800 ring-1 ring-exp-300">DEMO · synthetic</span>;
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-3 p-6 text-sm text-slate-500">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-teal-600" />
      {label}
    </div>
  );
}

export function ErrorBox({ message }: { message: string }) {
  return (
    <div role="alert" className="rounded-lg border border-issue-200 bg-issue-50 px-4 py-3 text-sm text-issue-700">
      {message}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-slate-300 px-4 py-8 text-center">
      <p className="text-sm font-medium text-navy-800">{title}</p>
      {children && <div className="mt-1 text-sm text-slate-500">{children}</div>}
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-navy-900 sm:text-2xl">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-slate-600">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export function Notice({ tone = "info", title, children }: { tone?: "info" | "exp" | "issue" | "flag"; title?: string; children: ReactNode }) {
  const cls = {
    info: "border-navy-700/15 bg-navy-900/[0.03] text-navy-800",
    exp: "border-exp-300 bg-exp-50 text-exp-800",
    issue: "border-issue-200 bg-issue-50 text-issue-700",
    flag: "border-flag-200 bg-flag-50 text-flag-700",
  }[tone];
  return (
    <div className={`rounded-lg border px-4 py-3 text-sm ${cls}`}>
      {title && <p className="mb-0.5 font-semibold">{title}</p>}
      <div>{children}</div>
    </div>
  );
}
