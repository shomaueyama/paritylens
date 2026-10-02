import Link from "next/link";

import { DeleteButton } from "@/components/delete-button";
import { buttonClass } from "@/components/ui/button";
import { Card, CardHeader, EmptyState } from "@/components/ui/card";
import { load, serverApi } from "@/lib/api/server";

type Step = { request: { method: string; path: string } };

export default async function TestCasesPage({
  params,
}: PageProps<"/projects/[projectId]/test-cases">) {
  const { projectId } = await params;
  const api = await serverApi();
  const cases = await load(
    api.GET("/api/v1/projects/{project_id}/test-cases", {
      params: { path: { project_id: projectId } },
    }),
  );

  return (
    <Card>
      <CardHeader
        title="Test cases"
        action={
          <Link href={`/projects/${projectId}/test-cases/new`} className={buttonClass("primary")}>
            New test case
          </Link>
        }
      />
      {cases.length === 0 ? (
        <EmptyState>
          A test case is a request, or a sequence of requests, sent to both APIs.
        </EmptyState>
      ) : (
        <ul className="divide-y divide-line">
          {cases.map((testCase) => {
            const steps = testCase.steps as Step[];
            return (
              <li key={testCase.id} className="flex items-center gap-4 px-4 py-3">
                <div className="min-w-0 flex-1">
                  <Link
                    href={`/projects/${projectId}/test-cases/${testCase.id}`}
                    className="font-medium hover:underline"
                  >
                    {testCase.name}
                  </Link>
                  <p className="truncate font-mono text-xs text-muted">
                    {steps.map((step) => `${step.request.method} ${step.request.path}`).join("  →  ")}
                  </p>
                </div>
                {testCase.enabled ? null : <span className="text-xs text-muted">not in runs</span>}
                <DeleteButton target={{ kind: "test-case", id: testCase.id }} />
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
