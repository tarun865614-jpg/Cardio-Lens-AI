import type { Proportion } from "./types";

export function fmtDate(iso: string | null | undefined, withTime = true): string {
  if (!iso) return "—";
  const d = new Date(iso.endsWith("Z") || /[+-]\d\d:\d\d$/.test(iso) ? iso : iso + "Z");
  return withTime
    ? d.toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export function humanize(s: string | null | undefined): string {
  if (!s) return "—";
  return s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

/** Format a proportion with its CI, or say explicitly that it was not evaluated. */
export function fmtProportion(p: Proportion | undefined | null, digits = 1): string {
  if (!p || p.value === null || p.value === undefined) return p?.reason ? `Not evaluated (${p.reason})` : "Not evaluated";
  const pct = (v: number) => (v * 100).toFixed(digits) + "%";
  const ci = p.ci_low !== null && p.ci_high !== null && p.ci_low !== undefined && p.ci_high !== undefined ? ` (95% CI ${pct(p.ci_low)}–${pct(p.ci_high)})` : "";
  const frac = p.k !== undefined && p.n !== undefined ? ` · ${p.k}/${p.n}` : "";
  return pct(p.value) + ci + frac;
}

export function fmtScore(v: number): string {
  return v.toFixed(2);
}

export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
