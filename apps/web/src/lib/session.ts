import "server-only";

import { load, serverApi } from "./api/server";
import type { Me } from "./api/types";

/**
 * The signed-in user, or a redirect to the login page.
 *
 * Called by the layout of every page that needs a session. The check that
 * actually protects data is the backend's; this only decides which page
 * to show.
 */
export async function requireUser(): Promise<Me> {
  const api = await serverApi();
  return load(api.GET("/api/v1/me"));
}
