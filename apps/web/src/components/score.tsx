import type { RunSummary } from "@/lib/api/types";
import { scoreText } from "@/lib/result";

/** The compatibility score, never shown without what it is a share of. */
export function Score({ summary }: { summary: RunSummary }) {
  const { percent, of } = scoreText(summary);
  return (
    <div>
      <p className="text-4xl font-semibold tabular-nums tracking-tight">{percent}</p>
      <p className="text-sm text-muted">{of}</p>
    </div>
  );
}

export function SummaryCounts({ summary }: { summary: RunSummary }) {
  const counts = [
    { label: "breaking", value: summary.breaking, style: "text-critical" },
    { label: "warning", value: summary.warning, style: "text-medium" },
    { label: "compatible", value: summary.compatible, style: "text-ok" },
    { label: "error", value: summary.error, style: "text-muted" },
  ];
  return (
    <dl className="flex gap-6 text-sm">
      {counts.map((count) => (
        <div key={count.label}>
          <dd className={`text-xl font-semibold tabular-nums ${count.style}`}>{count.value}</dd>
          <dt className="text-muted">{count.label}</dt>
        </div>
      ))}
    </dl>
  );
}
