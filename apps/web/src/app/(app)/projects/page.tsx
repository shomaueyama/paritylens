import type { Metadata } from "next";
import Link from "next/link";

import { buttonClass } from "@/components/ui/button";
import { Card, EmptyState } from "@/components/ui/card";
import { load, serverApi } from "@/lib/api/server";

export const metadata: Metadata = { title: "Projects" };

export default async function ProjectsPage() {
  const api = await serverApi();
  const projects = await load(api.GET("/api/v1/projects"));

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold tracking-tight">Projects</h1>
        <Link href="/projects/new" className={buttonClass("primary")}>
          New project
        </Link>
      </div>

      {projects.length === 0 ? (
        <Card>
          <EmptyState>
            No projects yet. A project pairs an old API with the new one replacing it.
          </EmptyState>
        </Card>
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2">
          {projects.map((project) => (
            <li key={project.id}>
              <Link
                href={`/projects/${project.id}`}
                className="block rounded-lg border border-line bg-surface p-4 hover:border-accent"
              >
                <h2 className="font-medium">{project.name}</h2>
                <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 font-mono text-xs text-muted">
                  <dt>old</dt>
                  <dd className="truncate">{project.old_base_url}</dd>
                  <dt>new</dt>
                  <dd className="truncate">{project.new_base_url}</dd>
                </dl>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
