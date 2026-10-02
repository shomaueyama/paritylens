import Link from "next/link";
import type { ReactNode } from "react";

import { SeverityBadge } from "@/components/badges";
import type { Analysis, Difference, Finding } from "@/lib/api/types";
import { changeText, hintText, kindText, reasonText } from "@/lib/result";

function remarksOf(difference: Difference): string[] {
  const reason = reasonText(difference.reason);
  return [...(reason ? [reason] : []), ...(difference.hints ?? []).map(hintText)];
}

/** The differences of one step. `action` renders something per row. */
export function DifferencesTable({
  differences,
  action,
}: {
  differences: Difference[];
  action?: (difference: Difference) => ReactNode;
}) {
  return (
    <ul className="divide-y divide-line">
      {differences.map((difference) => {
        const remarks = remarksOf(difference);
        return (
          <li
            key={difference.id}
            className="grid gap-x-4 gap-y-1 px-4 py-3 md:grid-cols-[6rem_1fr_auto]"
          >
            <div>
              <SeverityBadge severity={difference.severity} />
            </div>
            <div className="min-w-0">
              <p className="text-sm">
                <span className="text-muted">{kindText(difference.kind)}</span>{" "}
                <code className="break-all font-semibold">{difference.path}</code>
              </p>
              <p className="break-all font-mono text-sm">{changeText(difference)}</p>
              {remarks.length > 0 ? (
                <p className="text-xs text-muted">{remarks.join(" ")}</p>
              ) : null}
            </div>
            {action ? <div>{action(difference)}</div> : null}
          </li>
        );
      })}
    </ul>
  );
}

const AI_VERDICT_STYLE: Record<Analysis["verdict"], string> = {
  breaking: "text-critical",
  warning: "text-medium",
  safe: "text-ok",
};

/**
 * What a language model said about a finding.
 *
 * Drawn apart from the severity on purpose: a dashed outline, its own
 * label, the model's name. The severity badge is the result; this is an
 * opinion about it, and the two can disagree.
 */
export function AiOpinion({ analysis }: { analysis: Analysis }) {
  return (
    <div className="mt-2 rounded-md border border-dashed border-line px-3 py-2 text-sm">
      <p className="text-xs text-muted">
        AI opinion ·{" "}
        <span className={`font-semibold ${AI_VERDICT_STYLE[analysis.verdict]}`}>
          {analysis.verdict}
        </span>{" "}
        · {analysis.confidence} confidence · {analysis.model}
      </p>
      <p className="mt-1">{analysis.explanation}</p>
    </div>
  );
}

/**
 * The findings of a whole run. Each is listed once, however many cases
 * it occurred in; the grouping is done by the backend.
 */
export function FindingsList({
  findings,
  runId,
  analyses = {},
}: {
  findings: Finding[];
  runId: string;
  analyses?: Record<string, Analysis>;
}) {
  return (
    <ul className="divide-y divide-line">
      {findings.map((finding) => {
        const remarks = remarksOf(finding.example);
        const analysis = analyses[finding.signature];
        const more = finding.case_count - finding.cases.length;
        return (
          <li
            key={`${finding.severity}|${finding.signature}`}
            className="grid gap-x-4 gap-y-1 px-4 py-3 md:grid-cols-[6rem_1fr]"
          >
            <div>
              <SeverityBadge severity={finding.severity} />
            </div>
            <div className="min-w-0">
              <p className="text-sm">
                <span className="text-muted">{kindText(finding.kind)}</span>{" "}
                <code className="break-all font-semibold">{finding.path}</code>
              </p>
              <p className="break-all font-mono text-sm">{changeText(finding.example)}</p>
              {remarks.length > 0 ? (
                <p className="text-xs text-muted">{remarks.join(" ")}</p>
              ) : null}
              <p className="mt-1 text-xs text-muted">
                {finding.case_count === 1 ? "In " : `In ${finding.case_count} cases: `}
                {finding.cases.map((testCase, index) => (
                  <span key={testCase.id}>
                    {index > 0 ? ", " : null}
                    <Link
                      href={`/runs/${runId}/cases/${testCase.id}`}
                      className="text-accent hover:underline"
                    >
                      {testCase.name}
                    </Link>
                  </span>
                ))}
                {more > 0 ? ` and ${more} more` : null}
              </p>
              {analysis ? <AiOpinion analysis={analysis} /> : null}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
