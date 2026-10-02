"use client";

import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/field";
import { api, send } from "@/lib/api/client";

export function TokenForm() {
  const router = useRouter();
  const [name, setName] = useState("");

  const create = useMutation({
    mutationFn: () => send(api.POST("/api/v1/api-tokens", { body: { name } })),
    // The result holds the token itself. Drop it from the cache as soon
    // as this component is gone, not minutes later.
    gcTime: 0,
    onSuccess: () => {
      setName("");
      router.refresh();
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate();
  }

  return (
    <div className="flex flex-col gap-3 p-4">
      <form onSubmit={submit} className="flex flex-wrap items-start gap-3">
        <div className="min-w-64 flex-1">
          <Field
            label="Name"
            htmlFor="token-name"
            hint="Where the token will be used, e.g. the name of a CI job."
            error={create.isError ? create.error.message : undefined}
          >
            <Input
              id="token-name"
              required
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </Field>
        </div>
        <div className="pt-6">
          <Button type="submit" variant="primary" disabled={create.isPending}>
            Create token
          </Button>
        </div>
      </form>
      {create.isSuccess ? (
        <div role="status" className="rounded-md bg-ok-soft p-3 text-sm">
          <p className="font-medium text-ok">Copy this token now. It is not shown again.</p>
          <code className="mt-1 block break-all">{create.data.token}</code>
        </div>
      ) : null}
    </div>
  );
}
