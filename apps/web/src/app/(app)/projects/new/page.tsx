import type { Metadata } from "next";

import { ProjectForm } from "@/components/forms/project-form";

export const metadata: Metadata = { title: "New project" };

export default function NewProjectPage() {
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold tracking-tight">New project</h1>
      <ProjectForm />
    </div>
  );
}
