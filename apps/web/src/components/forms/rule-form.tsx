"use client";

import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/field";
import { api, send } from "@/lib/api/client";
import type { RuleCreate } from "@/lib/api/types";

const KINDS: { value: RuleCreate["kind"]; label: string; hint: string; placeholder: string }[] = [
  {
    value: "ignore",
    label: "Ignore",
    hint: "Differences at this path are kept but do not count.",
    placeholder: "$..request_id",
  },
  {
    value: "unordered",
    label: "Unordered array",
    hint: "Compare this array without regard to order. A key pairs elements up.",
    placeholder: "$.items",
  },
  {
    value: "critical",
    label: "Critical",
    hint: "Any difference at this path is critical.",
    placeholder: "$..settlement_amount",
  },
  {
    value: "compare_header",
    label: "Compare header",
    hint: "Headers are not compared unless listed here.",
    placeholder: "ETag",
  },
];

export function RuleForm({ projectId }: { projectId: string }) {
  const router = useRouter();
  const [kind, setKind] = useState<RuleCreate["kind"]>("ignore");
  const [path, setPath] = useState("");
  const [key, setKey] = useState("");
  const selected = KINDS.find((option) => option.value === kind) ?? KINDS[0];

  const create = useMutation({
    mutationFn: () =>
      send(
        api.POST("/api/v1/projects/{project_id}/rules", {
          params: { path: { project_id: projectId } },
          body: { kind, path, ...(kind === "unordered" && key.trim() ? { key: key.trim() } : {}) },
        }),
      ),
    onSuccess: () => {
      setPath("");
      setKey("");
      router.refresh();
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate();
  }

  return (
    <form onSubmit={submit} className="flex flex-wrap items-start gap-3 p-4">
      <Field label="Kind" htmlFor="kind">
        <select
          id="kind"
          value={kind}
          onChange={(event) => setKind(event.target.value as RuleCreate["kind"])}
          className="rounded-md border border-line bg-surface px-2 py-1.5 text-sm"
        >
          {KINDS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </Field>
      <div className="min-w-64 flex-1">
        <Field
          label={kind === "compare_header" ? "Header name" : "Path"}
          htmlFor="path"
          hint={selected.hint}
          error={create.isError ? create.error.message : undefined}
        >
          <Input
            id="path"
            required
            className="font-mono"
            value={path}
            onChange={(event) => setPath(event.target.value)}
            placeholder={selected.placeholder}
          />
        </Field>
      </div>
      {kind === "unordered" ? (
        <Field label="Key (optional)" htmlFor="key">
          <Input
            id="key"
            className="font-mono"
            value={key}
            onChange={(event) => setKey(event.target.value)}
            placeholder="sku"
          />
        </Field>
      ) : null}
      <div className="pt-6">
        <Button type="submit" variant="primary" disabled={create.isPending}>
          Add rule
        </Button>
      </div>
    </form>
  );
}
