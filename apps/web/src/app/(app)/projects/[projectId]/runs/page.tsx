import Link from "next/link";

import { RunStatusBadge } from "@/components/badges";
import { RunButton } from "@/components/run-button";
import { Card, CardHeader, EmptyState } from "@/components/ui/card";
import { load, serverApi } from "@/lib/api/server";
import { formatDateTime, scoreText } from "@/lib/result";

export default async function RunsPage({
  params,
  searchParams,
}: PageProps<"/projects/[projectId]/runs">) {
  const { projectId } = await params;
  const before = (await searchParams).before;
  const api = await serverApi();
  const page = await load(
    api.GET("/api/v1/projects/{project_id}/runs", {
      params: {
        path: { project_id: projectId },
        query: { limit: 20, ...(typeof before === "string" ? { before } : {}) },
      },
    }),
  );
  const runs = page.runs;

  return (
    <Card>
      <CardHeader title="Runs" action={<RunButton projectId={projectId} />} />
      {runs.length === 0 ? (
        <EmptyState>No runs yet.</EmptyState>
      ) : (
        <ul className="divide-y divide-line">
          {runs.map((run) => (
            <li key={run.id}>
              <Link
                href={`/runs/${run.id}`}
                className="flex flex-wrap items-center gap-4 px-4 py-3 text-sm hover:bg-neutral-soft"
              >
                <span className="w-24">
                  <RunStatusBadge status={run.status} />
                </span>
                <span className="w-16 font-semibold tabular-nums">
                  {run.summary ? scoreText(run.summary).percent : ""}
                </span>
                <span className="flex-1 text-muted">
                  {run.summary
                    ? `${run.summary.breaking} breaking · ${run.summary.warning} warning · ${run.summary.error} error`
                    : (run.error ?? "")}
                </span>
                <span className="text-xs text-muted">{run.source === "cli" ? "CLI" : "server"}</span>
                <span className="text-xs text-muted">{formatDateTime(run.created_at)}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      {page.next_cursor ? (
        <p className="border-t border-line px-4 py-3 text-sm">
          <Link
            href={`/projects/${projectId}/runs?before=${page.next_cursor}`}
            className="text-accent hover:underline"
          >
            Older runs
          </Link>
        </p>
      ) : null}
    </Card>
  );
}
