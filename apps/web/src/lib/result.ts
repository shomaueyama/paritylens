/**
 * How results are worded and coloured. One place, so the run page, the
 * case page and the tests all agree.
 */
import type { RunSummary } from "./api/types";

export const SEVERITIES = ["none", "low", "medium", "high", "critical"] as const;
export type Severity = (typeof SEVERITIES)[number];

export const VERDICTS = ["compatible", "warning", "breaking", "error"] as const;
export type Verdict = (typeof VERDICTS)[number];

export function severityRank(severity: string): number {
  return SEVERITIES.indexOf(severity as Severity);
}

export const SEVERITY_STYLE: Record<Severity, string> = {
  critical: "bg-critical-soft text-critical",
  high: "bg-high-soft text-high",
  medium: "bg-medium-soft text-medium",
  low: "bg-low-soft text-low",
  none: "bg-neutral-soft text-muted",
};

export const VERDICT_STYLE: Record<Verdict, string> = {
  compatible: "bg-ok-soft text-ok",
  warning: "bg-medium-soft text-medium",
  breaking: "bg-critical-soft text-critical",
  error: "bg-neutral-soft text-muted",
};

const KIND_TEXT: Record<string, string> = {
  status_changed: "Status changed",
  body_format_changed: "Body format changed",
  header_changed: "Header changed",
  field_added: "Field added",
  field_removed: "Field removed",
  type_changed: "Type changed",
  value_changed: "Value changed",
  array_changed: "Array changed",
};

const REASON_TEXT: Record<string, string> = {
  critical_rule: "Marked critical by a rule.",
  critical_field_name: "The field name reads like an amount of money.",
  outcome_flipped: "One API succeeded where the other failed.",
  ignore_rule: "Ignored by a rule.",
  volatile_in_baseline: "Also changes between two calls to the old API.",
  tracks_request_time: "It is the time of the request.",
};

const NOTE_TEXT: Record<string, string> = {
  body_not_compared_status_class:
    "Bodies were not compared: one response is a success and the other is not.",
  body_not_compared_truncated: "Bodies were not compared: too large to read in full.",
  baseline_unstable: "The old API returned different statuses to the same request.",
  baseline_unavailable: "Noise detection was unavailable: the repeat request failed.",
  differences_truncated: "Only the most severe differences are shown; there were more.",
};

const HINT_TEXT: Record<string, string> = {
  looks_like_uuid: "Both values look like generated IDs.",
  looks_like_timestamp: "Both values look like timestamps.",
  baseline_also_differs: "The old API itself is not stable here.",
};

const sentence = (table: Record<string, string>) => (key: string) => table[key] ?? key;

export const kindText = sentence(KIND_TEXT);
export const reasonText = (reason: string): string | null => REASON_TEXT[reason] ?? null;
export const noteText = sentence(NOTE_TEXT);
export const hintText = sentence(HINT_TEXT);

/** Cases that produced a result to judge. Errors are evidence of nothing. */
export function evaluatedCases(summary: RunSummary): number {
  return summary.total - summary.error;
}

/**
 * The compatibility score as text, always with its denominator.
 *
 * "94%" alone invites reading it as "94% of the API is compatible". It is
 * 94% of the cases that were run, and the wording has to say so.
 */
export function scoreText(summary: RunSummary): { percent: string; of: string } {
  const evaluated = evaluatedCases(summary);
  if (evaluated === 0) {
    return { percent: "—", of: "no case could be evaluated" };
  }
  const percent = Math.floor((summary.compatible / evaluated) * 100);
  return { percent: `${percent}%`, of: `${summary.compatible} of ${evaluated} cases compatible` };
}

/** What a difference changed, in one line. */
export function changeText(difference: {
  kind: string;
  /** The values as exact JSON text, from the API. */
  old_text?: string;
  new_text?: string;
  detail?: string | null;
}): string {
  const oldText = difference.old_text ?? "";
  const newText = difference.new_text ?? "";
  switch (difference.kind) {
    case "field_added":
      return `added ${newText}`;
    case "field_removed":
      return `removed (was ${oldText})`;
    case "array_changed":
      return difference.detail ?? "elements differ";
    default:
      return `${oldText} → ${newText}`;
  }
}

/**
 * A timestamp as text, in UTC and labelled as such.
 *
 * Pages are rendered on the server, which does not know the reader's
 * time zone. Formatting in the server's own zone would print a time that
 * is right somewhere and unlabelled everywhere.
 */
export function formatDateTime(iso: string): string {
  const text = new Intl.DateTimeFormat("en-GB", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(new Date(iso));
  return `${text} UTC`;
}

/**
 * What identifies a finding within a run: its signature at a severity.
 * The same field can be noise in one case and a real change in another,
 * and those are two findings. An AI opinion is about exactly one of them.
 */
export function findingKey(finding: { signature: string; severity: string }): string {
  return `${finding.severity}|${finding.signature}`;
}
