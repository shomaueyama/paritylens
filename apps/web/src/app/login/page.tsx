import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { buttonClass } from "@/components/ui/button";
import { serverApi } from "@/lib/api/server";

import { DevLoginForm } from "./dev-login-form";

export const metadata: Metadata = { title: "Sign in" };

export default async function LoginPage({ searchParams }: PageProps<"/login">) {
  const failed = (await searchParams).error === "sign_in_failed";

  // This page has to render even when the backend is down: it is where
  // people land when something is wrong.
  let mode: "dev" | "google" | undefined;
  let signedIn = false;
  try {
    const api = await serverApi();
    const [me, config] = await Promise.all([
      api.GET("/api/v1/me"),
      api.GET("/api/v1/auth/config"),
    ]);
    signedIn = me.response.ok;
    mode = config.data?.mode;
  } catch {
    // fetch threw: the API could not be reached at all.
  }
  // Already signed in? Then there is nothing to do here. (Outside the
  // try block: redirect() works by throwing.)
  if (signedIn) redirect("/projects");

  return (
    <main className="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center gap-6 px-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">ParityLens</h1>
        <p className="mt-1 text-sm text-muted">
          Checks that a rewritten API still behaves like the one it replaces.
        </p>
      </div>

      {failed ? (
        <p role="alert" className="rounded-md bg-critical-soft px-3 py-2 text-sm text-critical">
          Sign-in did not complete. Please try again.
        </p>
      ) : null}

      {!mode ? (
        <p role="alert" className="text-sm text-critical">
          The API is not reachable.
        </p>
      ) : mode === "google" ? (
        // A plain link: the browser has to leave for Google and come back.
        <a href="/api/v1/auth/google/login" className={buttonClass("primary")}>
          Sign in with Google
        </a>
      ) : (
        <DevLoginForm />
      )}
    </main>
  );
}
