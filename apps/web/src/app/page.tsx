import { ApiStatus } from "@/components/api-status";
import { getApiHealth } from "@/lib/api-health";

// A Server Component: this function runs on the server for each request,
// so it can await the backend directly and ship only HTML to the browser.
export default async function HomePage() {
  const health = await getApiHealth();

  return (
    <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col justify-center gap-6 px-4 py-16">
      <h1 className="text-3xl font-semibold tracking-tight">ParityLens</h1>
      <p className="text-neutral-600 dark:text-neutral-400">
        Checks that a rewritten API still behaves like the one it replaces.
      </p>
      <ApiStatus health={health} />
    </main>
  );
}
