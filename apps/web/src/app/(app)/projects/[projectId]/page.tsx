import Link from "next/link";

import { RunStatusBadge } from "@/components/badges";
import { RunButton } from "@/components/run-button";
import { Score, SummaryCounts } from "@/components/score";
import { Card, CardHeader, EmptyState } from "@/components/ui/card";
import { load, serverApi } from "@/lib/api/server";
import { getProject } from "@/lib/project";
import { formatDateTime } from "@/lib/result";

export default async function ProjectOverviewPage({
  params,
}: PageProps<"/projects/[projectId]">) {
  const { projectId } = await params;
  const project = await getProject(projectId);
  const api = await serverApi();
  const path = { project_id: project.id };

  // Independent requests, sent together rather than one after another.
  const [cases, runPage] = await Promise.all([
    load(api.GET("/api/v1/projects/{project_id}/test-cases", { params: { path } })),
    load(api.GET("/api/v1/projects/{project_id}/runs", { params: { path, query: { limit: 1 } } })),
  ]);
  const enabled = cases.filter((testCase) => testCase.enabled).length;
  const latest = runPage.runs.at(0);

  return (
    <div className="grid items-start gap-4 lg:grid-cols-[2fr_1fr]">
      <Card>
        <CardHeader
          title="Latest run"
          action={
            latest ? (
              <Link href={`/runs/${latest.id}`} className="text-sm text-accent hover:underline">
                Open
              </Link>
            ) : null
          }
        />
        {latest?.summary ? (
          <div className="flex flex-wrap items-end justify-between gap-6 p-4">
            <Score summary={latest.summary} />
            <SummaryCounts summary={latest.summary} />
          </div>
        ) : latest ? (
          <p className="flex items-center gap-2 p-4 text-sm">
            <RunStatusBadge status={latest.status} />
            {latest.error ?? `Requested ${formatDateTime(latest.created_at)}`}
          </p>
        ) : (
          <EmptyState>This project has not been run yet.</EmptyState>
        )}
      </Card>

      <Card>
        <CardHeader title="Run" />
        <div className="flex flex-col gap-3 p-4 text-sm">
          <p className="text-muted">
            {enabled === 0
              ? "Add a test case first. A run sends each one to both APIs."
              : `${enabled} test ${enabled === 1 ? "case" : "cases"} will be sent to both APIs.`}
          </p>
          <RunButton projectId={project.id} disabled={enabled === 0} />
          {project.description ? <p className="text-muted">{project.description}</p> : null}
        </div>
      </Card>
    </div>
  );
}
