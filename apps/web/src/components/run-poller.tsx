"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { api } from "@/lib/api/client";

const POLL_MS = 1500;

/** What the page is waiting for: the run itself, then its AI analysis. */
type Progress = { status: string; aiStatus: string };

/** Whether there is nothing left to wait for. */
export function isSettled({ status, aiStatus }: Progress): boolean {
  const runDone = status === "completed" || status === "failed";
  const analysisPending = aiStatus === "pending" || aiStatus === "running";
  return runDone && !(status === "completed" && analysisPending);
}

function message({ status, aiStatus }: Progress): string {
  if (status === "queued") return "Waiting for a worker…";
  if (status === "running") return "Sending requests to both APIs…";
  return aiStatus === "pending" ? "Waiting for AI analysis…" : "AI analysis in progress…";
}

/**
 * Watches a run that has not settled and reloads the page when it changes.
 *
 * The page itself is a Server Component and renders once per request.
 * This small Client Component is what keeps asking; when something
 * changes, router.refresh() has the server render the page again.
 */
export function RunPoller({ runId, status, aiStatus }: { runId: string } & Progress) {
  const router = useRouter();
  const shown: Progress = { status, aiStatus };
  const { data } = useQuery({
    // The state is part of the key, so a result cached for an earlier
    // state of this run is never mistaken for the current one.
    queryKey: ["run-progress", runId, status, aiStatus],
    queryFn: async (): Promise<Progress | "gone"> => {
      const { data: run, response } = await api.GET("/api/v1/runs/{run_id}", {
        params: { path: { run_id: runId } },
      });
      // Deleted, or the session ended. Not "still running": stop asking
      // and let the server decide what page this is now.
      if (response.status === 404 || response.status === 401) return "gone";
      return run ? { status: run.status, aiStatus: run.ai_status } : shown;
    },
    initialData: shown,
    // A settled run will not change again; do not ask about it at all.
    enabled: !isSettled(shown),
    refetchInterval: (query) => {
      const latest = query.state.data;
      return latest === "gone" || (latest && isSettled(latest)) ? false : POLL_MS;
    },
  });

  const changed =
    data === "gone" || data.status !== status || data.aiStatus !== aiStatus;
  useEffect(() => {
    if (changed) router.refresh();
  }, [changed, router]);

  if (isSettled(shown)) return null;
  return (
    <p role="status" className="rounded-md bg-low-soft px-3 py-2 text-sm text-low">
      {message(shown)}
    </p>
  );
}
