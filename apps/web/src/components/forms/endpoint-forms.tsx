"use client";

import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/button";
import { Field, Input, Textarea } from "@/components/ui/field";
import { api, send } from "@/lib/api/client";
import { METHODS } from "@/lib/schemas";

export function EndpointForm({ projectId }: { projectId: string }) {
  const router = useRouter();
  const [method, setMethod] = useState<(typeof METHODS)[number]>("GET");
  const [path, setPath] = useState("");

  const create = useMutation({
    mutationFn: () =>
      send(
        api.POST("/api/v1/projects/{project_id}/endpoints", {
          params: { path: { project_id: projectId } },
          body: { method, path_template: path },
        }),
      ),
    onSuccess: () => {
      setPath("");
      router.refresh();
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate();
  }

  return (
    <form onSubmit={submit} className="flex flex-wrap items-start gap-3 p-4">
      <Field label="Method" htmlFor="endpoint-method">
        <select
          id="endpoint-method"
          value={method}
          onChange={(event) => setMethod(event.target.value as (typeof METHODS)[number])}
          className="rounded-md border border-line bg-surface px-2 py-1.5 text-sm"
        >
          {METHODS.map((option) => (
            <option key={option}>{option}</option>
          ))}
        </select>
      </Field>
      <div className="min-w-64 flex-1">
        <Field
          label="Path"
          htmlFor="endpoint-path"
          error={create.isError ? create.error.message : undefined}
        >
          <Input
            id="endpoint-path"
            required
            className="font-mono"
            value={path}
            onChange={(event) => setPath(event.target.value)}
            placeholder="/customers/{id}"
          />
        </Field>
      </div>
      <div className="pt-6">
        <Button type="submit" variant="primary" disabled={create.isPending}>
          Add endpoint
        </Button>
      </div>
    </form>
  );
}

export function OpenApiImportForm({ projectId }: { projectId: string }) {
  const router = useRouter();
  const [document, setDocument] = useState("");

  const run = useMutation({
    mutationFn: () =>
      send(
        api.POST("/api/v1/projects/{project_id}/openapi", {
          params: { path: { project_id: projectId } },
          body: { document },
        }),
      ),
    onSuccess: () => {
      setDocument("");
      router.refresh();
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    run.mutate();
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-3 p-4">
      <Field
        label="OpenAPI document"
        htmlFor="openapi"
        hint="Paste JSON or YAML. Every operation in it is added as an endpoint."
        error={run.isError ? run.error.message : undefined}
      >
        <Textarea
          id="openapi"
          required
          rows={6}
          spellCheck={false}
          value={document}
          onChange={(event) => setDocument(event.target.value)}
        />
      </Field>
      <div className="flex items-center gap-3">
        <Button type="submit" disabled={run.isPending}>
          {run.isPending ? "Importing…" : "Import"}
        </Button>
        {run.isSuccess ? (
          <p role="status" className="text-sm text-muted">
            Added {run.data.created}, already present {run.data.already_present}.
          </p>
        ) : null}
      </div>
    </form>
  );
}
