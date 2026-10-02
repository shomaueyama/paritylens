"use client";

import { useMutation } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { api, send } from "@/lib/api/client";

export function SignOutButton() {
  const signOut = useMutation({
    mutationFn: () => send(api.POST("/api/v1/auth/logout")),
    // A full page load, not a client-side navigation: everything the
    // browser still holds about the signed-in user is thrown away. That
    // is exactly what the lint rule below advises against in general.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    onSuccess: () => window.location.assign("/login"),
  });

  return (
    <span className="inline-flex items-center gap-2">
      {signOut.isError ? (
        <span role="alert" className="text-xs text-critical">
          {signOut.error.message}
        </span>
      ) : null}
      <Button variant="ghost" onClick={() => signOut.mutate()} disabled={signOut.isPending}>
        Sign out
      </Button>
    </span>
  );
}
