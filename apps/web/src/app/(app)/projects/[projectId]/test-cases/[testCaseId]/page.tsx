import { notFound } from "next/navigation";

import { TestCaseForm } from "@/components/forms/test-case-form";
import { load, serverApi } from "@/lib/api/server";
import type { TestCase } from "@/lib/api/types";
import { parseJson } from "@/lib/json";
import { testCaseToForm } from "@/lib/schemas";

export default async function EditTestCasePage({
  params,
}: PageProps<"/projects/[projectId]/test-cases/[testCaseId]">) {
  const { projectId, testCaseId } = await params;
  const api = await serverApi();
  // Read as text and parsed without rounding: a JSON body in a test case
  // may hold 9007199254740993 or 1.0, and must be shown, and saved again,
  // exactly so. The form receives plain strings prepared here.
  const text = await load(
    api.GET("/api/v1/test-cases/{test_case_id}", {
      params: { path: { test_case_id: testCaseId } },
      parseAs: "text",
    }),
  );
  const testCase = parseJson(text) as TestCase;
  // The case must belong to the project in the URL, not merely exist.
  if (testCase.project_id !== projectId) notFound();

  return (
    <TestCaseForm
      projectId={projectId}
      existing={{
        id: testCase.id,
        endpointId: testCase.endpoint_id,
        values: testCaseToForm(testCase),
      }}
    />
  );
}
