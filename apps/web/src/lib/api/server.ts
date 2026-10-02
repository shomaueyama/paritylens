import "server-only";

import { cookies } from "next/headers";
import { notFound, redirect } from "next/navigation";
import createClient from "openapi-fetch";

import type { paths } from "./schema";

const apiInternalUrl = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

/**
 * An API client for Server Components.
 *
 * A Server Component runs on the Next.js server, not in the browser, so
 * the user's session cookie has to be passed along by hand: it is read
 * from the incoming request and attached to the request to the backend.
 * The backend, not this app, decides what that cookie is allowed to see.
 */
export async function serverApi() {
  const cookieStore = await cookies();
  return createClient<paths>({
    baseUrl: apiInternalUrl,
    headers: { cookie: cookieStore.toString() },
    // Everything here is per-user and changes often. Never cache it.
    cache: "no-store",
  });
}

type Result<T> = { data?: T; response: Response };

/**
 * The data of a backend response, or the right page for what went wrong.
 *
 * Every Server Component fetch goes through this. Reading `data` directly
 * and defaulting it to an empty list would show "nothing here yet" when
 * the truth is "the request failed", which is a worse lie than an error.
 *
 *   401            → the login page (the session ended)
 *   404, 422       → the not-found page (unknown or malformed ID)
 *   anything else  → an error, shown by the nearest error.tsx
 */
export async function load<T>(request: Promise<Result<T>>): Promise<T> {
  const { data, response } = await request;
  if (response.status === 401) redirect("/login");
  if (response.status === 404 || response.status === 422) notFound();
  if (!response.ok || data === undefined) {
    throw new Error(`The API answered ${response.status}.`);
  }
  return data;
}
