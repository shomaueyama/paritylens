import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { VerdictBadge } from "@/components/badges";
import { DifferencesTable } from "@/components/differences-table";
import { IgnoreButton } from "@/components/ignore-button";
import { Card, CardHeader } from "@/components/ui/card";
import { load, serverApi } from "@/lib/api/server";
import type { StepResult } from "@/lib/api/types";
import { prettyBody } from "@/lib/json";
import { noteText, severityRank } from "@/lib/result";

export const metadata: Metadata = { title: "Case result" };

type Side = StepResult["old"];

function SidePanel({ label, side }: { label: string; side: Side }) {
  const { request, response } = side;
  return (
    <div className="min-w-0">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">{label}</h3>
      {side.skipped ? <p className="text-sm text-muted">Not sent: {side.skipped}</p> : null}
      {side.error ? <p className="text-sm text-critical">{side.error}</p> : null}
      {request ? (
        <p className="break-all font-mono text-xs text-muted">
          {request.method} {request.url}
        </p>
      ) : null}
      {response ? (
        <>
          <p className="mt-2 text-sm">
            <span className="font-mono font-semibold">{response.status}</span>
            {response.duration_ms != null ? (
              <span className="text-muted"> · {Math.round(response.duration_ms)} ms</span>
            ) : null}
            {response.body_truncated ? <span className="text-muted"> · body cut short</span> : null}
          </p>
          <pre className="mt-2 max-h-96 overflow-auto rounded-md bg-neutral-soft p-3 font-mono text-xs">
            {prettyBody(response.body) || "(no body)"}
          </pre>
        </>
      ) : null}
    </div>
  );
}

export default async function CaseResultPage({
  params,
}: PageProps<"/runs/[runId]/cases/[caseResultId]">) {
  const { runId, caseResultId } = await params;
  const api = await serverApi();
  const [result, run] = await Promise.all([
    load(
      api.GET("/api/v1/case-results/{case_result_id}", {
        params: { path: { case_result_id: caseResultId } },
      }),
    ),
    load(api.GET("/api/v1/runs/{run_id}", { params: { path: { run_id: runId } } })),
  ]);
  // The URL names a run and a case; they have to belong together.
  if (result.run_id !== run.id) notFound();

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold tracking-tight">{result.name}</h1>
        <VerdictBadge verdict={result.verdict} />
        <Link href={`/runs/${run.id}`} className="text-sm text-accent hover:underline">
          Back to the run
        </Link>
      </div>

      {result.steps.map((step) => {
        const findings = step.differences
          .filter((d) => d.severity !== "none")
          .sort((a, b) => severityRank(b.severity) - severityRank(a.severity));
        const noise = step.differences.filter((d) => d.severity === "none");
        return (
          <Card key={step.id}>
            <CardHeader title={`${step.step_id} · ${step.outcome}`} />
            {step.notes.length > 0 ? (
              <ul className="border-b border-line px-4 py-2 text-sm text-muted">
                {step.notes.map((note) => (
                  <li key={note}>{noteText(note)}</li>
                ))}
              </ul>
            ) : null}
            {findings.length > 0 ? (
              <div className="border-b border-line">
                <DifferencesTable
                  differences={findings}
                  action={(difference) =>
                    // Only differences inside a JSON body have a pattern.
                    difference.pattern ? (
                      <IgnoreButton projectId={run.project_id} pattern={difference.pattern} />
                    ) : null
                  }
                />
              </div>
            ) : null}
            {noise.length > 0 ? (
              <p className="border-b border-line px-4 py-2 text-xs text-muted">
                Set aside as noise: {noise.map((difference) => difference.path).join(", ")}
              </p>
            ) : null}
            <div className="grid gap-4 p-4 lg:grid-cols-2">
              <SidePanel label="Old API" side={step.old} />
              <SidePanel label="New API" side={step.new} />
            </div>
          </Card>
        );
      })}
    </div>
  );
}
