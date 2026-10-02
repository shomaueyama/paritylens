import { TestCaseForm } from "@/components/forms/test-case-form";

export default async function NewTestCasePage({
  params,
}: PageProps<"/projects/[projectId]/test-cases/new">) {
  const { projectId } = await params;
  return <TestCaseForm projectId={projectId} />;
}
