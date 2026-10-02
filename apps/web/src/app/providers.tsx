"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";

/**
 * Client-side providers. TanStack Query keeps a cache of server data in
 * the browser; it is used here for the things a Server Component cannot
 * do: polling a run until it finishes, and tracking a mutation's progress.
 */
export function Providers({ children }: { children: ReactNode }) {
  // useState, not a module-level constant: on the server each request
  // must get its own cache, or one user's data could reach another.
  const [client] = useState(() => new QueryClient());
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
