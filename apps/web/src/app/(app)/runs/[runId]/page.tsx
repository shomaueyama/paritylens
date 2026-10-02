import type { Metadata } from "next";
import Link from "next/link";

import { AnalyseButton } from "@/components/analyse-button";
import { RunStatusBadge, VerdictBadge } from "@/components/badges";
import { FindingsList } from "@/components/differences-table";
import { RunPoller } from "@/components/run-poller";
import { Score, SummaryCounts } from "@/components/score";
import { Card, CardHeader, EmptyState } from "@/components/ui/card";
import { load, serverApi } from "@/lib/api/server";
import type { Analysis } from "@/lib/api/types";
import { getProject } from "@/lib/project";
import { formatDateTime, reasonText, severityRank } from "@/lib/result";

export const metadata: Metadata = { title: "Run" };

export default async function RunPage({ params }: PageProps<"/runs/[runId]">) {
  const { runId } = await params;
  const api = await serverApi();
  const path = { run_id: runId };
  const [run, { findings, truncated }, features] = await Promise.all([
    load(api.GET("/api/v1/runs/{run_id}", { params: { path } })),
    load(api.GET("/api/v1/runs/{run_id}/findings", { params: { path } })),
    load(api.GET("/api/v1/features")),
  ]);
  const project = await getProject(run.project_id);

  const breaking = findings.filter((f) => severityRank(f.severity) >= severityRank("medium"));
  const minor = findings.filter((f) => f.severity === "low");
  const safe = findings.filter((f) => f.severity === "none");
  const analyses: Record<string, Analysis> = Object.fromEntries(
    run.analyses.map((analysis) => [analysis.signature, analysis]),
  );

  const aiAvailable = project.ai_enabled && features.ai_provider !== "none";
  const aiIdle = !["pending", "running"].includes(run.ai_status);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold tracking-tight">Compatibility result</h1>
        <RunStatusBadge status={run.status} />
        <Link
          href={`/projects/${run.project_id}/runs`}
          className="text-sm text-accent hover:underline"
        >
          All runs
        </Link>
      </div>
      <p className="font-mono text-xs text-muted">
        {run.old_base_url} → {run.new_base_url} ·{" "}
        {run.source === "cli" ? "uploaded from the CLI" : "run on the server"} ·{" "}
        {formatDateTime(run.created_at)}
      </p>

      <RunPoller runId={run.id} status={run.status} aiStatus={run.ai_status} />
      {run.status === "failed" ? (
        <p role="alert" className="rounded-md bg-critical-soft px-3 py-2 text-sm text-critical">
          The run failed: {run.error ?? "unknown error"}
        </p>
      ) : null}

      {run.summary ? (
        <>
          <Card>
            <div className="flex flex-wrap items-end justify-between gap-6 p-4">
              <Score summary={run.summary} />
              <SummaryCounts summary={run.summary} />
            </div>
          </Card>

          {truncated ? (
            <p role="status" className="rounded-md bg-medium-soft px-3 py-2 text-sm text-medium">
              This run has more distinct findings than can be listed. The most severe are shown.
            </p>
          ) : null}

          {aiAvailable ? (
            <div className="flex flex-wrap items-center gap-3 text-sm text-muted">
              {run.ai_status === "failed" ? (
                <span role="alert" className="text-critical">
                  AI analysis failed: {run.ai_error ?? "unknown error"}
                </span>
              ) : run.ai_status === "completed" ? (
                <span>
                  AI opinions are advisory. They do not change severities, verdicts or the score.
                </span>
              ) : null}
              {aiIdle && run.status === "completed" ? (
                <AnalyseButton runId={run.id} again={run.ai_status === "completed"} />
              ) : null}
            </div>
          ) : null}

          <Card>
            <CardHeader title={`Potential breaking changes (${breaking.length})`} />
            {breaking.length === 0 ? (
              <EmptyState>None found in the cases that were run.</EmptyState>
            ) : (
              <FindingsList findings={breaking} runId={run.id} analyses={analyses} />
            )}
          </Card>

          {minor.length > 0 ? (
            <Card>
              <CardHeader title={`Low-severity differences (${minor.length})`} />
              <FindingsList findings={minor} runId={run.id} analyses={analyses} />
            </Card>
          ) : null}

          <Card>
            <CardHeader title={`Safe differences (${safe.length})`} />
            {safe.length === 0 ? (
              <EmptyState>No values were set aside as noise.</EmptyState>
            ) : (
              <ul className="divide-y divide-line">
                {safe.map((finding) => (
                  <li key={finding.signature} className="flex flex-wrap gap-x-4 px-4 py-2 text-sm">
                    <code className="font-semibold">{finding.path}</code>
                    <span className="text-muted">{reasonText(finding.example.reason)}</span>
                    <span className="ml-auto text-xs text-muted">
                      {finding.count} {finding.count === 1 ? "time" : "times"}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card>
            <CardHeader title={`Cases (${run.cases.length})`} />
            <ul className="divide-y divide-line">
              {run.cases.map((testCase) => (
                <li key={testCase.id} className="flex items-center gap-3 px-4 py-2 text-sm">
                  <span className="w-28 shrink-0">
                    <VerdictBadge verdict={testCase.verdict} />
                  </span>
                  <Link
                    href={`/runs/${run.id}/cases/${testCase.id}`}
                    className="min-w-0 flex-1 truncate hover:underline"
                  >
                    {testCase.name}
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
        </>
      ) : null}
    </div>
  );
}
