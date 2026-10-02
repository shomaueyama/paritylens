import type { ApiHealth } from "@/lib/api-health";

const LABELS: Record<ApiHealth, string> = {
  up: "API is up",
  down: "API is not reachable",
};

const DOT_COLORS: Record<ApiHealth, string> = {
  up: "bg-emerald-500",
  down: "bg-red-500",
};

/** Shows backend health. Takes the result as a prop so it stays a plain, testable component. */
export function ApiStatus({ health }: { health: ApiHealth }) {
  return (
    <p role="status" className="flex items-center gap-2 text-sm">
      <span aria-hidden className={`size-2 rounded-full ${DOT_COLORS[health]}`} />
      {LABELS[health]}
    </p>
  );
}
