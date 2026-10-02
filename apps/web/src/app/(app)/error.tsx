"use client";

import { Button } from "@/components/ui/button";

/**
 * Shown when a page under this layout throws while rendering, which here
 * means a backend request failed. An error boundary has to be a Client
 * Component: it holds state, and `reset` re-renders the page.
 */
export default function AppError({ reset }: { error: Error; reset: () => void }) {
  return (
    <div role="alert" className="mx-auto flex max-w-md flex-col items-start gap-3 py-16">
      <h1 className="text-xl font-semibold tracking-tight">This page could not be loaded</h1>
      <p className="text-sm text-muted">
        The server did not answer as expected. Nothing was changed. This is not the same as
        there being nothing to show.
      </p>
      <Button onClick={reset}>Try again</Button>
    </div>
  );
}
