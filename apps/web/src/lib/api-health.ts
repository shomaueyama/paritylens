export type ApiHealth = "up" | "down";

const apiInternalUrl = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

/**
 * Asks the backend whether it is alive. Runs on the server only.
 *
 * Any failure (network error, timeout, non-2xx) is reported as "down"
 * instead of thrown: the page should still render when the API is not.
 */
export async function getApiHealth(): Promise<ApiHealth> {
  try {
    const response = await fetch(`${apiInternalUrl}/api/v1/health`, {
      // Health is only meaningful right now, so never serve a cached answer.
      cache: "no-store",
      signal: AbortSignal.timeout(2000),
    });
    return response.ok ? "up" : "down";
  } catch {
    return "down";
  }
}
