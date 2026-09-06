import type { ReactNode } from "react";

export function Card({ title, aside, children, className = "" }: {
  title?: ReactNode; aside?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <section className={`card ${className}`}>
      {title && (
        <h2>
          {title}
          {aside && <span style={{ marginLeft: "auto", textTransform: "none", letterSpacing: 0 }}>{aside}</span>}
        </h2>
      )}
      {children}
    </section>
  );
}

export function Stat({ value, label, tone, small }: {
  value: ReactNode; label: string; tone?: Tone; small?: boolean;
}) {
  return (
    <div className={`stat${small ? " small" : ""}`}>
      <div className="value" style={tone ? { color: `var(--${toneVar(tone)})` } : undefined}>{value}</div>
      <div className="label">{label}</div>
    </div>
  );
}

export type Tone = "ok" | "warn" | "bad" | "crit" | "muted";

function toneVar(tone: Tone): string {
  return tone === "muted" ? "muted" : tone;
}

export function Badge({ tone = "muted", dot, children }: {
  tone?: Tone; dot?: boolean; children: ReactNode;
}) {
  return <span className={`badge ${tone}${dot ? " dot" : ""}`}>{children}</span>;
}

/** Health strings map to a single tone vocabulary across every panel. */
export function healthTone(health: string): Tone {
  if (health === "ok") return "ok";
  if (health === "degraded") return "warn";
  if (health === "unavailable") return "bad";
  return "muted";
}

export function riskTone(risk: string | null | undefined): Tone {
  switch (risk) {
    case "critical": return "crit";
    case "high": return "bad";
    case "medium": return "warn";
    case "low": return "ok";
    default: return "muted";
  }
}

/** L2 outcome vocabulary. `skipped_l1` is a success, not a warning. */
export function outcomeTone(outcome: string): Tone {
  switch (outcome) {
    case "called": return "ok";
    case "heartbeat": return "muted";
    case "skipped_l1": return "muted";
    case "forced_high_risk": return "warn";
    case "failed": return "bad";
    case "degraded_text_only": return "warn";
    case "not_required": return "muted";
    default: return "muted";
  }
}

export function ms(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (value < 1000) return `${Math.round(value)} ms`;
  return `${(value / 1000).toFixed(1)} s`;
}

export function clock(at: number | string | null | undefined): string {
  if (at === null || at === undefined) return "—";
  const date = typeof at === "number" ? new Date(at) : new Date(at);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

/**
 * One phrasing for every failed call.
 *
 * The Dashboard uses `Promise.allSettled` and degrades panel by panel; the
 * other pages issue single calls, and a rejection there used to be swallowed
 * by `void`. An empty page then read as "nothing has happened yet" — the one
 * thing a care UI must never say when it simply could not ask.
 */
export function errorText(exc: unknown): string {
  const error = exc as { code?: string; message?: string } | null;
  const code = error?.code && error.code !== "unknown" ? `（${error.code}）` : "";
  return `${error?.message || "無法連線至後端"}${code}`;
}

/** A failure the caregiver needs to see, in the same slot on every page. */
export function ErrorBanner({ children }: { children: ReactNode }) {
  return <p className="banner bad" role="alert">{children}</p>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="empty">{children}</p>;
}
