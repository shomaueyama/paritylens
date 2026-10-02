"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/button";
import { Field, Input, Textarea } from "@/components/ui/field";
import { api, send } from "@/lib/api/client";
import type { Project } from "@/lib/api/types";
import { type ProjectForm as Values, projectSchema } from "@/lib/schemas";

/**
 * Creates a project, or edits one when `project` is given.
 *
 * React Hook Form keeps the field values and errors; Zod decides what is
 * valid. Components only render. This is the pattern for every form here.
 */
export function ProjectForm({ project }: { project?: Project }) {
  const router = useRouter();
  const [serverError, setServerError] = useState<string>();
  const [done, setDone] = useState(false);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<Values>({
    resolver: zodResolver(projectSchema),
    defaultValues: {
      name: project?.name ?? "",
      description: project?.description ?? "",
      old_base_url: project?.old_base_url ?? "",
      new_base_url: project?.new_base_url ?? "",
    },
  });

  async function save(values: Values) {
    setServerError(undefined);
    try {
      const saved = await send(
        project
          ? api.PATCH("/api/v1/projects/{project_id}", {
              params: { path: { project_id: project.id } },
              body: values,
            })
          : api.POST("/api/v1/projects", { body: values }),
      );
      // Stay disabled until the next page is showing: a second click
      // during navigation would create a second project.
      setDone(true);
      router.push(`/projects/${saved.id}`);
      // Server Components do not re-fetch on their own; this asks them to.
      router.refresh();
    } catch (error) {
      setServerError((error as Error).message);
    }
  }

  return (
    <form onSubmit={handleSubmit(save)} className="flex max-w-xl flex-col gap-4" noValidate>
      <Field label="Name" htmlFor="name" error={errors.name?.message}>
        <Input id="name" {...register("name")} aria-invalid={errors.name ? true : undefined} />
      </Field>
      <Field
        label="Old API base URL"
        htmlFor="old_base_url"
        hint="The system being replaced."
        error={errors.old_base_url?.message}
      >
        <Input
          id="old_base_url"
          placeholder="https://legacy.example.com"
          {...register("old_base_url")}
          aria-invalid={errors.old_base_url ? true : undefined}
        />
      </Field>
      <Field
        label="New API base URL"
        htmlFor="new_base_url"
        hint="The system replacing it."
        error={errors.new_base_url?.message}
      >
        <Input
          id="new_base_url"
          placeholder="https://modern.example.com"
          {...register("new_base_url")}
          aria-invalid={errors.new_base_url ? true : undefined}
        />
      </Field>
      <Field label="Description" htmlFor="description" error={errors.description?.message}>
        <Textarea id="description" rows={3} className="font-sans" {...register("description")} />
      </Field>
      {serverError ? (
        <p role="alert" className="text-sm text-critical">
          {serverError}
        </p>
      ) : null}
      <div>
        <Button type="submit" variant="primary" disabled={isSubmitting || (done && !project)}>
          {isSubmitting ? "Saving…" : project ? "Save changes" : "Create project"}
        </Button>
      </div>
    </form>
  );
}
