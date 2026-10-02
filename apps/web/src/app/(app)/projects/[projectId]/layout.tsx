import { getProject } from "@/lib/project";

import { ProjectTabs } from "./tabs";

export default async function ProjectLayout({
  children,
  params,
}: LayoutProps<"/projects/[projectId]">) {
  const { projectId } = await params;
  const project = await getProject(projectId);

  return (
    <div className="flex flex-col gap-5">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{project.name}</h1>
        <p className="mt-1 font-mono text-xs text-muted">
          {project.old_base_url} → {project.new_base_url}
        </p>
      </div>
      <ProjectTabs projectId={project.id} />
      {children}
    </div>
  );
}
