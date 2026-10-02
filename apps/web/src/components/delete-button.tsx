"use client";

import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { api, send } from "@/lib/api/client";

type Target =
  | { kind: "rule"; id: string }
  | { kind: "endpoint"; id: string }
  | { kind: "test-case"; id: string }
  | { kind: "token"; id: string }
  | { kind: "secret"; projectId: string; name: string }
  | { kind: "project"; id: string };

async function remove(target: Target) {
  switch (target.kind) {
    case "rule":
      return api.DELETE("/api/v1/rules/{rule_id}", { params: { path: { rule_id: target.id } } });
    case "endpoint":
      return api.DELETE("/api/v1/endpoints/{endpoint_id}", {
        params: { path: { endpoint_id: target.id } },
      });
    case "test-case":
      return api.DELETE("/api/v1/test-cases/{test_case_id}", {
        params: { path: { test_case_id: target.id } },
      });
    case "token":
      return api.DELETE("/api/v1/api-tokens/{token_id}", {
        params: { path: { token_id: target.id } },
      });
    case "secret":
      return api.DELETE("/api/v1/projects/{project_id}/secrets/{name}", {
        params: { path: { project_id: target.projectId, name: target.name } },
      });
    case "project":
      return api.DELETE("/api/v1/projects/{project_id}", {
        params: { path: { project_id: target.id } },
      });
  }
}

/**
 * Deletes one thing and refreshes the page it was listed on.
 *
 * The target is described by data, not passed as a function: a Server
 * Component renders this button, and functions cannot cross from the
 * server to the browser.
 */
export function DeleteButton({
  target,
  label = "Delete",
  confirm,
  redirectTo,
}: {
  target: Target;
  label?: string;
  confirm?: string;
  redirectTo?: string;
}) {
  const router = useRouter();
  const deletion = useMutation({
    mutationFn: () => send(remove(target) as Promise<{ response: Response }>),
    onSuccess: () => {
      if (redirectTo) router.push(redirectTo);
      router.refresh();
    },
  });

  return (
    <span className="inline-flex items-center gap-2">
      <Button
        variant={confirm ? "danger" : "ghost"}
        disabled={deletion.isPending}
        onClick={() => {
          if (!confirm || window.confirm(confirm)) deletion.mutate();
        }}
      >
        {deletion.isPending ? "Deleting…" : label}
      </Button>
      {deletion.isError ? (
        <span role="alert" className="text-xs text-critical">
          {deletion.error.message}
        </span>
      ) : null}
    </span>
  );
}
