"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/field";
import { api, send } from "@/lib/api/client";

/** Local development only: sign in by typing any email address. */
export function DevLoginForm() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string>();
  const [pending, setPending] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(undefined);
    try {
      await send(api.POST("/api/v1/auth/dev-login", { body: { email } }));
      router.push("/projects");
      router.refresh();
    } catch (problem) {
      setError((problem as Error).message);
      // Only on failure: after success the button stays disabled until
      // the next page has replaced this one.
      setPending(false);
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-3">
      <Field
        label="Email"
        htmlFor="email"
        hint="Development sign-in: any address works, no password."
        error={error}
      >
        <Input
          id="email"
          type="email"
          required
          autoFocus
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          placeholder="you@example.com"
          aria-invalid={error ? true : undefined}
        />
      </Field>
      <Button type="submit" variant="primary" disabled={pending}>
        {pending ? "Signing in…" : "Sign in"}
      </Button>
    </form>
  );
}
