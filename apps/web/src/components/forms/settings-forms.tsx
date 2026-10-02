"use client";

import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/button";
import { Field, Input, Textarea } from "@/components/ui/field";
import { api, send } from "@/lib/api/client";
import type { Project } from "@/lib/api/types";
import { formatHeaders, invalidHeaderLines, parseHeaders } from "@/lib/schemas";

/** Headers sent to each API. A credential is referred to by name, never typed here. */
export function HeadersForm({ project }: { project: Project }) {
  const router = useRouter();
  const [oldHeaders, setOldHeaders] = useState(formatHeaders(project.old_headers));
  const [newHeaders, setNewHeaders] = useState(formatHeaders(project.new_headers));

  const save = useMutation({
    mutationFn: async () => {
      // A line without a colon would be skipped, which on save means a
      // header quietly deleted. Refuse instead.
      const invalid = [...invalidHeaderLines(oldHeaders), ...invalidHeaderLines(newHeaders)];
      if (invalid.length > 0) {
        throw new Error(`Not written as "Name: value": ${invalid[0]}`);
      }
      return send(
        api.PATCH("/api/v1/projects/{project_id}", {
          params: { path: { project_id: project.id } },
          body: { old_headers: parseHeaders(oldHeaders), new_headers: parseHeaders(newHeaders) },
        }),
      );
    },
    onSuccess: () => router.refresh(),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-3 p-4">
      <p className="text-sm text-muted">
        One per line, as <code>Name: value</code>. To send a stored secret, write{" "}
        <code>{"{{secret.NAME}}"}</code> where its value should go.
      </p>
      <div className="grid gap-3 lg:grid-cols-2">
        <Field label="Sent to the old API" htmlFor="old-headers">
          <Textarea
            id="old-headers"
            rows={4}
            spellCheck={false}
            value={oldHeaders}
            onChange={(event) => setOldHeaders(event.target.value)}
            placeholder="Authorization: Bearer {{secret.OLD_TOKEN}}"
          />
        </Field>
        <Field label="Sent to the new API" htmlFor="new-headers">
          <Textarea
            id="new-headers"
            rows={4}
            spellCheck={false}
            value={newHeaders}
            onChange={(event) => setNewHeaders(event.target.value)}
            placeholder="Authorization: Bearer {{secret.NEW_TOKEN}}"
          />
        </Field>
      </div>
      <div className="flex items-center gap-3">
        <Button type="submit" disabled={save.isPending}>
          Save headers
        </Button>
        {save.isError ? (
          <p role="alert" className="text-sm text-critical">
            {save.error.message}
          </p>
        ) : null}
        {save.isSuccess ? (
          <p role="status" className="text-sm text-muted">
            Saved.
          </p>
        ) : null}
      </div>
    </form>
  );
}

/** Stores a secret. The value goes to the server and is never shown again. */
export function SecretForm({ projectId }: { projectId: string }) {
  const router = useRouter();
  const [name, setName] = useState("");
  const [value, setValue] = useState("");

  const save = useMutation({
    mutationFn: () =>
      send(
        api.PUT("/api/v1/projects/{project_id}/secrets/{name}", {
          params: { path: { project_id: projectId, name } },
          body: { value },
        }),
      ),
    onSuccess: () => {
      setName("");
      setValue("");
      router.refresh();
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <form onSubmit={submit} className="flex flex-wrap items-start gap-3 p-4">
      <Field label="Name" htmlFor="secret-name" hint="Letters, digits, underscores.">
        <Input
          id="secret-name"
          required
          className="font-mono"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="SHOP_TOKEN"
        />
      </Field>
      <div className="min-w-64 flex-1">
        <Field
          label="Value"
          htmlFor="secret-value"
          hint="Stored encrypted. It cannot be read back, only replaced."
          error={save.isError ? save.error.message : undefined}
        >
          <Input
            id="secret-value"
            required
            // password: not shown on screen, and not offered by autocomplete.
            type="password"
            autoComplete="off"
            value={value}
            onChange={(event) => setValue(event.target.value)}
          />
        </Field>
      </div>
      <div className="pt-6">
        <Button type="submit" variant="primary" disabled={save.isPending}>
          Save secret
        </Button>
      </div>
    </form>
  );
}

/** Opt a project in to, or out of, AI analysis. */
export function AiForm({ project, provider }: { project: Project; provider: string }) {
  const router = useRouter();
  // Shown as changed at once, and put back if the server refuses.
  const [enabled, setEnabled] = useState(project.ai_enabled);
  const toggle = useMutation({
    mutationFn: (value: boolean) =>
      send(
        api.PATCH("/api/v1/projects/{project_id}", {
          params: { path: { project_id: project.id } },
          body: { ai_enabled: value },
        }),
      ),
    onSuccess: () => router.refresh(),
    onError: () => setEnabled(project.ai_enabled),
  });

  return (
    <div className="flex flex-col gap-3 p-4 text-sm">
      <label className="flex items-start gap-2">
        <input
          type="checkbox"
          className="mt-1"
          checked={enabled}
          disabled={toggle.isPending}
          onChange={(event) => {
            setEnabled(event.target.checked);
            toggle.mutate(event.target.checked);
          }}
        />
        <span>
          Explain differences with AI
          <span className="block text-xs text-muted">
            After each run, the differences it found (field paths and example values from the
            responses, shortened) are sent to the model provider, which says whether each is
            likely to matter. Stored secrets and noise are not sent. The opinions are shown next
            to the results and never change them.
          </span>
        </span>
      </label>
      <p className="text-xs text-muted">
        {provider === "none"
          ? "This deployment has no AI provider configured, so nothing will be sent."
          : `Provider configured for this deployment: ${provider}.`}
      </p>
      {toggle.isError ? (
        <p role="alert" className="text-critical">
          {toggle.error.message}
        </p>
      ) : null}
    </div>
  );
}
