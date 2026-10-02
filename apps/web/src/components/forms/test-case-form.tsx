"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useFieldArray, useForm } from "react-hook-form";

import { Button } from "@/components/ui/button";
import { Field, Input, Textarea } from "@/components/ui/field";
import { api, send } from "@/lib/api/client";
import type { TestCaseWrite } from "@/lib/api/types";
import { stringifyJson } from "@/lib/json";
import {
  EMPTY_STEP,
  METHODS,
  stepFromForm,
  type TestCaseForm as Values,
  testCaseSchema,
} from "@/lib/schemas";

/**
 * Creates a test case, or edits one when `existing` is given.
 *
 * `existing.values` is prepared on the server (see the edit page), where
 * the stored JSON can be read without rounding its numbers.
 */
export function TestCaseForm({
  projectId,
  existing,
}: {
  projectId: string;
  existing?: { id: string; endpointId: string | null; values: Values };
}) {
  const router = useRouter();
  const [serverError, setServerError] = useState<string>();
  const [done, setDone] = useState(false);
  const {
    control,
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<Values>({
    resolver: zodResolver(testCaseSchema),
    defaultValues: existing?.values ?? {
      name: "",
      noise_detection: true,
      enabled: true,
      steps: [EMPTY_STEP],
    },
  });
  // A list of sub-forms whose length changes: steps can be added and removed.
  const steps = useFieldArray({ control, name: "steps" });

  async function save(values: Values) {
    setServerError(undefined);
    const body = {
      name: values.name,
      // The form has no field for this; it is carried so that saving
      // does not detach the case from its endpoint.
      endpoint_id: existing?.endpointId ?? null,
      noise_detection: values.noise_detection,
      enabled: values.enabled,
      steps: values.steps.map(stepFromForm),
    } as TestCaseWrite;
    // Written out with stringifyJson so that numbers in a JSON body are
    // sent exactly as typed.
    const bodySerializer = (value: unknown) => stringifyJson(value);
    try {
      await send(
        existing
          ? api.PUT("/api/v1/test-cases/{test_case_id}", {
              params: { path: { test_case_id: existing.id } },
              body,
              bodySerializer,
            })
          : api.POST("/api/v1/projects/{project_id}/test-cases", {
              params: { path: { project_id: projectId } },
              body,
              bodySerializer,
            }),
      );
      setDone(true);
      router.push(`/projects/${projectId}/test-cases`);
      router.refresh();
    } catch (error) {
      // The server checks what the form cannot, such as a {{variable}}
      // used before any step captures it.
      setServerError((error as Error).message);
    }
  }

  return (
    <form onSubmit={handleSubmit(save)} className="flex flex-col gap-5" noValidate>
      <div className="max-w-xl">
        <Field label="Name" htmlFor="name" error={errors.name?.message}>
          <Input id="name" {...register("name")} aria-invalid={errors.name ? true : undefined} />
        </Field>
      </div>

      <ol className="flex flex-col gap-4">
        {steps.fields.map((step, index) => {
          const stepErrors = errors.steps?.[index];
          return (
            <li key={step.id} className="rounded-lg border border-line bg-surface p-4">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-sm font-semibold">Step {index + 1}</h2>
                {steps.fields.length > 1 ? (
                  <Button variant="ghost" onClick={() => steps.remove(index)}>
                    Remove step
                  </Button>
                ) : null}
              </div>
              <input type="hidden" {...register(`steps.${index}.rest`)} />
              <div className="grid gap-3 sm:grid-cols-[8rem_1fr_12rem]">
                <Field label="Method" htmlFor={`steps.${index}.method`}>
                  <select
                    id={`steps.${index}.method`}
                    {...register(`steps.${index}.method`)}
                    className="rounded-md border border-line bg-surface px-2 py-1.5 text-sm"
                  >
                    {METHODS.map((method) => (
                      <option key={method}>{method}</option>
                    ))}
                  </select>
                </Field>
                <Field
                  label="Path"
                  htmlFor={`steps.${index}.path`}
                  hint="Use {{name}} for a value captured by an earlier step."
                  error={stepErrors?.path?.message}
                >
                  <Input
                    id={`steps.${index}.path`}
                    className="font-mono"
                    {...register(`steps.${index}.path`)}
                    aria-invalid={stepErrors?.path ? true : undefined}
                  />
                </Field>
                <Field label="Step id (optional)" htmlFor={`steps.${index}.id`}>
                  <Input id={`steps.${index}.id`} {...register(`steps.${index}.id`)} />
                </Field>
              </div>
              <div className="mt-3 grid gap-3 lg:grid-cols-2">
                <Field
                  label="JSON body (optional)"
                  htmlFor={`steps.${index}.json`}
                  error={stepErrors?.json?.message}
                >
                  <Textarea
                    id={`steps.${index}.json`}
                    rows={5}
                    spellCheck={false}
                    {...register(`steps.${index}.json`)}
                    aria-invalid={stepErrors?.json ? true : undefined}
                  />
                </Field>
                <Field
                  label="Capture (optional)"
                  htmlFor={`steps.${index}.capture`}
                  hint="One per line: order_id = $.id   Add (secret) to mask a captured token."
                  error={stepErrors?.capture?.message}
                >
                  <Textarea
                    id={`steps.${index}.capture`}
                    rows={5}
                    spellCheck={false}
                    {...register(`steps.${index}.capture`)}
                    aria-invalid={stepErrors?.capture ? true : undefined}
                  />
                </Field>
              </div>
            </li>
          );
        })}
      </ol>

      <div>
        <Button onClick={() => steps.append(EMPTY_STEP)} disabled={steps.fields.length >= 20}>
          Add step
        </Button>
      </div>

      <fieldset className="flex flex-col gap-2 text-sm">
        <label className="flex items-center gap-2">
          <input type="checkbox" {...register("enabled")} />
          Include in runs
        </label>
        <label className="flex items-start gap-2">
          <input type="checkbox" className="mt-1" {...register("noise_detection")} />
          <span>
            Detect noise by sending each request to the old API twice
            <span className="block text-xs text-muted">
              Turn off for requests that must not be repeated.
            </span>
          </span>
        </label>
      </fieldset>

      {serverError ? (
        <p role="alert" className="text-sm text-critical">
          {serverError}
        </p>
      ) : null}
      <div>
        <Button type="submit" variant="primary" disabled={isSubmitting || done}>
          {isSubmitting ? "Saving…" : existing ? "Save changes" : "Create test case"}
        </Button>
      </div>
    </form>
  );
}
