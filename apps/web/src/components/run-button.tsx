"use client";

import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { api, send } from "@/lib/api/client";

/** Queues a run and goes to its page, where the result appears when it is ready. */
export function RunButton({ projectId, disabled }: { projectId: string; disabled?: boolean }) {
  const router = useRouter();
  const start = useMutation({
    mutationFn: () =>
      send(
        api.POST("/api/v1/projects/{project_id}/runs", {
          params: { path: { project_id: projectId } },
        }),
      ),
    onSuccess: (run) => router.push(`/runs/${run.id}`),
  });

  return (
    <div className="flex items-center gap-3">
      <Button
        variant="primary"
        onClick={() => start.mutate()}
        // Disabled through success as well: the run page is on its way,
        // and a second click would queue a second run.
        disabled={disabled || start.isPending || start.isSuccess}
      >
        {start.isPending ? "Starting…" : "Run now"}
      </Button>
      {start.isError ? (
        <p role="alert" className="text-sm text-critical">
          {start.error.message}
        </p>
      ) : null}
    </div>
  );
}
