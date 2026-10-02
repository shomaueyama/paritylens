"use client";

import { useMutation } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { api, send } from "@/lib/api/client";

/**
 * Turns a difference into an ignore rule.
 *
 * This is how a judgement ("that one does not matter") becomes part of
 * the deterministic comparison: as a rule a person approved, written
 * down, and visible on the Rules page. Nothing is hidden silently.
 *
 * `pattern` comes from the backend, which knows the path grammar. The
 * browser does not try to rewrite paths itself.
 */
export function IgnoreButton({ projectId, pattern }: { projectId: string; pattern: string }) {
  const add = useMutation({
    mutationFn: () =>
      send(
        api.POST("/api/v1/projects/{project_id}/rules", {
          params: { path: { project_id: projectId } },
          body: { kind: "ignore", path: pattern },
        }),
      ),
  });

  if (add.isSuccess) {
    return (
      <span role="status" className="text-xs text-muted">
        Ignored from the next run on.
      </span>
    );
  }
  return (
    <span className="inline-flex flex-col items-end gap-1">
      <Button
        variant="ghost"
        disabled={add.isPending}
        onClick={() => add.mutate()}
        title={`Adds the rule: ignore ${pattern}`}
      >
        Ignore this
      </Button>
      {add.isError ? (
        <span role="alert" className="text-xs text-critical">
          {add.error.message}
        </span>
      ) : null}
    </span>
  );
}
