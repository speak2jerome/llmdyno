// Formatting helpers shared by every page.
export const fmtBytes = (b?: number | null, digits = 1) => {
  if (b === undefined || b === null || isNaN(b)) return "–";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let v = b;
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(i >= 3 ? digits : 0)} ${u[i]}`;
};
export const fmtMib = (m?: number | null, digits = 1) => (m === undefined || m === null ? "–" : `${(m / 1024).toFixed(digits)} GB`);
export const fmtNum = (n?: number | null, digits = 0) =>
  n === undefined || n === null || isNaN(n) ? "–" : n.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits });
export const fmtTokens = (n?: number | null) => {
  if (n === undefined || n === null) return "–";
  if (n >= 1e6) return `${(n / 1e6).toFixed(n >= 1e7 ? 0 : 1)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(n >= 1e4 ? 0 : 1)}k`;
  return String(Math.round(n));
};
export const fmtPct = (v?: number | null, digits = 0) => (v === undefined || v === null || isNaN(v) ? "–" : `${(v * 100).toFixed(digits)}%`);
export const fmtScore = (v?: number | null, digits = 0) => (v === undefined || v === null || isNaN(v) ? "–" : (v * 100).toFixed(digits));
export const fmtUsd = (v?: number | null) => {
  if (v === undefined || v === null) return "–";
  if (v === 0) return "$0";
  if (v < 0.01) return `$${v.toFixed(4)}`;
  if (v < 10) return `$${v.toFixed(2)}`;
  return `$${v.toFixed(0)}`;
};
export const fmtDur = (s?: number | null) => {
  if (s === undefined || s === null || isNaN(s)) return "–";
  if (s < 60) return `${s.toFixed(s < 10 ? 1 : 0)}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${Math.round(s % 60)}s`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
};
export const fmtMin = (m?: number | null) => (m === undefined || m === null ? "–" : m < 60 ? `${Math.round(m)} min` : `${(m / 60).toFixed(1)} h`);
export const fmtAgo = (ts?: number | null) => {
  if (!ts) return "–";
  const d = Date.now() / 1000 - ts;
  if (d < 60) return "just now";
  if (d < 3600) return `${Math.floor(d / 60)} min ago`;
  if (d < 86400) return `${Math.floor(d / 3600)} h ago`;
  return new Date(ts * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric", year: d > 300 * 86400 ? "numeric" : undefined });
};
export const fmtDate = (ts?: number | null) =>
  ts ? new Date(ts * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "–";
export const fmtCtx = (n?: number | null) => (!n ? "–" : n % 1024 === 0 ? `${n / 1024}k` : `${Math.round(n / 1000)}k`);
export const plural = (n: number, w: string, p?: string) => `${n} ${n === 1 ? w : p || w + "s"}`;
export const cls = (...a: (string | false | null | undefined)[]) => a.filter(Boolean).join(" ");
export const pick = <T,>(arr: T[], i: number) => arr[i % arr.length];
export const PALETTE = ["--c1", "--c2", "--c3", "--c4", "--c5", "--c6", "--c7", "--c8", "--c9", "--c10"];
export const cssVar = (v: string) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
export const scoreColor = (v?: number | null) =>
  v === undefined || v === null ? "var(--text-3)" : v >= 0.85 ? "var(--ok)" : v >= 0.65 ? "var(--info)" : v >= 0.45 ? "var(--warn)" : "var(--danger)";
