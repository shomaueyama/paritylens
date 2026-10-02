import "server-only";

import { cache } from "react";

import { load, serverApi } from "./api/server";
import type { Project } from "./api/types";

/**
 * The project for a page, or the 404 page.
 *
 * Wrapped in React's cache(): the layout and the page both need the
 * project, and within one request they share a single fetch.
 *
 * A malformed ID, an unknown one, and one in another workspace all end
 * at the same not-found page, as they do in the backend.
 */
export const getProject = cache(async (projectId: string): Promise<Project> => {
  const api = await serverApi();
  return load(
    api.GET("/api/v1/projects/{project_id}", { params: { path: { project_id: projectId } } }),
  );
});
