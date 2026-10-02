import createClient from "openapi-fetch";

import type { paths } from "./schema";

/**
 * The API client for Client Components.
 *
 * It calls this app's own origin; next.config.ts forwards /api/* to the
 * backend. The browser attaches the session cookie by itself, and adds
 * the Origin header the backend checks on every state-changing request.
 */
export const api = createClient<paths>({ baseUrl: "" });

/** The human-readable message of an RFC 9457 problem response. */
export function problemMessage(error: unknown, fallback = "Something went wrong."): string {
  if (typeof error === "object" && error !== null) {
    const problem = error as { detail?: unknown; title?: unknown; errors?: unknown };
    if (Array.isArray(problem.errors) && problem.errors.length > 0) {
      const first = problem.errors[0] as { location?: string; message?: string };
      return [first.location, first.message].filter(Boolean).join(": ");
    }
    if (typeof problem.detail === "string") return problem.detail;
    if (typeof problem.title === "string") return problem.title;
  }
  return fallback;
}

type Result<T> = { data?: T; error?: unknown; response: Response };

/**
 * Await an API call from the browser and return its data, or throw an
 * Error whose message can be shown to the user.
 *
 * Success is decided by the HTTP status, not by whether an error body
 * came back: a gateway can answer 502 with no body at all, and that must
 * not be mistaken for "saved".
 */
export async function send<T>(request: Promise<Result<T>>): Promise<T> {
  let result: Result<T>;
  try {
    result = await request;
  } catch {
    // fetch itself failed: offline, DNS, connection reset.
    throw new Error("Could not reach the server. Check your connection and try again.");
  }
  const { data, error, response } = result;
  if (response.status === 401) {
    // The session ended in another tab or expired. Start over at the
    // login page, with a full load so no signed-in state lingers.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.assign("/login");
    throw new Error("Your session has ended. Sign in again.");
  }
  if (!response.ok) {
    throw new Error(problemMessage(error, `The server answered ${response.status}.`));
  }
  return data as T;
}
