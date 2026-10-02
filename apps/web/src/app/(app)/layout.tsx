import Link from "next/link";

import { requireUser } from "@/lib/session";

import { SignOutButton } from "./sign-out-button";

/**
 * The frame around every signed-in page. Being a Server Component, it
 * fetches the user before anything is sent to the browser; a visitor
 * without a valid session never receives the page at all.
 */
export default async function AppLayout({ children }: LayoutProps<"/">) {
  const user = await requireUser();

  return (
    <>
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex w-full max-w-6xl items-center gap-6 px-4 py-3">
          <Link href="/projects" className="font-semibold tracking-tight">
            ParityLens
          </Link>
          <nav className="flex flex-1 gap-4 text-sm text-muted">
            <Link href="/projects" className="hover:text-foreground">
              Projects
            </Link>
            <Link href="/settings/tokens" className="hover:text-foreground">
              API tokens
            </Link>
          </nav>
          <span className="hidden text-sm text-muted sm:inline">{user.email}</span>
          <SignOutButton />
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">{children}</main>
    </>
  );
}
