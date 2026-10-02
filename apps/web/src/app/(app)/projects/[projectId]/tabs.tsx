"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  { label: "Overview", path: "" },
  { label: "Test cases", path: "/test-cases" },
  { label: "Rules", path: "/rules" },
  { label: "Endpoints", path: "/endpoints" },
  { label: "Runs", path: "/runs" },
  { label: "Settings", path: "/settings" },
];

/** A Client Component only because it reads the current URL to mark the active tab. */
export function ProjectTabs({ projectId }: { projectId: string }) {
  const pathname = usePathname();
  const base = `/projects/${projectId}`;

  return (
    <nav className="flex gap-1 overflow-x-auto border-b border-line" aria-label="Project">
      {TABS.map((tab) => {
        const href = base + tab.path;
        const active = tab.path === "" ? pathname === base : pathname.startsWith(href);
        return (
          <Link
            key={tab.label}
            href={href}
            aria-current={active ? "page" : undefined}
            className={`-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm ${
              active
                ? "border-accent font-medium text-foreground"
                : "border-transparent text-muted hover:text-foreground"
            }`}
          >
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}
