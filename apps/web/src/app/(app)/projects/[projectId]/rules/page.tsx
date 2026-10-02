import { DeleteButton } from "@/components/delete-button";
import { RuleForm } from "@/components/forms/rule-form";
import { Card, CardHeader, EmptyState } from "@/components/ui/card";
import { load, serverApi } from "@/lib/api/server";

const KIND_LABEL: Record<string, string> = {
  ignore: "Ignore",
  unordered: "Unordered",
  critical: "Critical",
  compare_header: "Compare header",
};

export default async function RulesPage({ params }: PageProps<"/projects/[projectId]/rules">) {
  const { projectId } = await params;
  const api = await serverApi();
  const rules = await load(
    api.GET("/api/v1/projects/{project_id}/rules", {
      params: { path: { project_id: projectId } },
    }),
  );

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader title="Add a rule" />
        <RuleForm projectId={projectId} />
      </Card>
      <Card>
        <CardHeader title="Rules" />
        {rules.length === 0 ? (
          <EmptyState>
            No rules. Values that change on every call are recognised without any.
          </EmptyState>
        ) : (
          <ul className="divide-y divide-line">
            {rules.map((rule) => (
              <li key={rule.id} className="flex items-center gap-4 px-4 py-2 text-sm">
                <span className="w-32 shrink-0 text-muted">{KIND_LABEL[rule.kind] ?? rule.kind}</span>
                <code className="min-w-0 flex-1 truncate">{rule.path}</code>
                {typeof rule.options.key === "string" ? (
                  <span className="text-xs text-muted">
                    key <code>{rule.options.key}</code>
                  </span>
                ) : null}
                <DeleteButton target={{ kind: "rule", id: rule.id }} label="Remove" />
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
