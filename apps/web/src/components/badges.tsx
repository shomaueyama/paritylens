import { SEVERITY_STYLE, type Severity, VERDICT_STYLE, type Verdict } from "@/lib/result";

const BADGE = "inline-block rounded px-1.5 py-0.5 text-xs font-semibold uppercase tracking-wide";

export function SeverityBadge({ severity }: { severity: string }) {
  const style = SEVERITY_STYLE[severity as Severity] ?? SEVERITY_STYLE.none;
  return <span className={`${BADGE} ${style}`}>{severity}</span>;
}

export function VerdictBadge({ verdict }: { verdict: string }) {
  const style = VERDICT_STYLE[verdict as Verdict] ?? VERDICT_STYLE.error;
  return <span className={`${BADGE} ${style}`}>{verdict}</span>;
}

const STATUS_STYLE: Record<string, string> = {
  queued: "bg-neutral-soft text-muted",
  running: "bg-low-soft text-low",
  completed: "bg-ok-soft text-ok",
  failed: "bg-critical-soft text-critical",
};

export function RunStatusBadge({ status }: { status: string }) {
  return <span className={`${BADGE} ${STATUS_STYLE[status] ?? STATUS_STYLE.queued}`}>{status}</span>;
}
