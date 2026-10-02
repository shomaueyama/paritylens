import { DeleteButton } from "@/components/delete-button";
import { ProjectForm } from "@/components/forms/project-form";
import { AiForm, HeadersForm, SecretForm } from "@/components/forms/settings-forms";
import { Card, CardHeader, EmptyState } from "@/components/ui/card";
import { load, serverApi } from "@/lib/api/server";
import { getProject } from "@/lib/project";
import { formatDateTime } from "@/lib/result";

export default async function SettingsPage({
  params,
}: PageProps<"/projects/[projectId]/settings">) {
  const { projectId } = await params;
  const project = await getProject(projectId);
  const api = await serverApi();
  const [secrets, features] = await Promise.all([
    load(
      api.GET("/api/v1/projects/{project_id}/secrets", {
        params: { path: { project_id: project.id } },
      }),
    ),
    load(api.GET("/api/v1/features")),
  ]);

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader title="Project" />
        <div className="p-4">
          <ProjectForm project={project} />
        </div>
      </Card>

      <Card>
        <CardHeader title="Request headers" />
        <HeadersForm project={project} />
      </Card>

      <Card>
        <CardHeader title="Secrets" />
        <SecretForm projectId={project.id} />
        {secrets.length === 0 ? (
          <EmptyState>Credentials for the APIs under test. None stored.</EmptyState>
        ) : (
          <ul className="divide-y divide-line border-t border-line">
            {secrets.map((secret) => (
              <li key={secret.name} className="flex items-center gap-4 px-4 py-2 text-sm">
                <code className="flex-1">{secret.name}</code>
                <span className="text-xs text-muted">
                  updated {formatDateTime(secret.updated_at)}
                </span>
                <DeleteButton
                  target={{ kind: "secret", projectId: project.id, name: secret.name }}
                  label="Remove"
                />
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card>
        <CardHeader title="AI analysis" />
        <AiForm project={project} provider={features.ai_provider} />
      </Card>

      <Card className="border-critical/40">
        <CardHeader title="Delete project" />
        <div className="flex items-center justify-between gap-4 p-4 text-sm">
          <p className="text-muted">Deletes the project with its test cases, rules and results.</p>
          <DeleteButton
            target={{ kind: "project", id: project.id }}
            label="Delete project"
            confirm={`Delete "${project.name}" and everything in it?`}
            redirectTo="/projects"
          />
        </div>
      </Card>
    </div>
  );
}
