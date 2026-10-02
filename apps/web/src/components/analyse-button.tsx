"use client";

import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { api, send } from "@/lib/api/client";

/** Queues the AI analysis of a completed run. */
export function AnalyseButton({ runId, again }: { runId: string; again: boolean }) {
  const router = useRouter();
  const request = useMutation({
    mutationFn: () =>
      send(api.POST("/api/v1/runs/{run_id}/analysis", { params: { path: { run_id: runId } } })),
    onSuccess: () => router.refresh(),
  });

  return (
    <span className="inline-flex items-center gap-2">
      <Button onClick={() => request.mutate()} disabled={request.isPending || request.isSuccess}>
        {again ? "Analyse again" : "Analyse with AI"}
      </Button>
      {request.isError ? (
        <span role="alert" className="text-xs text-critical">
          {request.error.message}
        </span>
      ) : null}
    </span>
  );
}
