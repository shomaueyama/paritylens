import { DeleteButton } from "@/components/delete-button";
import { EndpointForm, OpenApiImportForm } from "@/components/forms/endpoint-forms";
import { Card, CardHeader, EmptyState } from "@/components/ui/card";
import { load, serverApi } from "@/lib/api/server";

export default async function EndpointsPage({
  params,
}: PageProps<"/projects/[projectId]/endpoints">) {
  const { projectId } = await params;
  const api = await serverApi();
  const endpoints = await load(
    api.GET("/api/v1/projects/{project_id}/endpoints", {
      params: { path: { project_id: projectId } },
    }),
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title="Add an endpoint" />
          <EndpointForm projectId={projectId} />
        </Card>
        <Card>
          <CardHeader title="Import from OpenAPI" />
          <OpenApiImportForm projectId={projectId} />
        </Card>
      </div>
      <Card>
        <CardHeader title={`Endpoints (${endpoints.length})`} />
        {endpoints.length === 0 ? (
          <EmptyState>The endpoints being migrated, as a checklist of what to cover.</EmptyState>
        ) : (
          <ul className="divide-y divide-line">
            {endpoints.map((endpoint) => (
              <li key={endpoint.id} className="flex items-center gap-4 px-4 py-2 text-sm">
                <span className="w-16 shrink-0 font-mono text-xs font-semibold">
                  {endpoint.method}
                </span>
                <code className="min-w-0 flex-1 truncate">{endpoint.path_template}</code>
                <span className="hidden truncate text-muted md:inline">{endpoint.summary}</span>
                <span className="text-xs text-muted">{endpoint.source}</span>
                <DeleteButton target={{ kind: "endpoint", id: endpoint.id }} label="Remove" />
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
