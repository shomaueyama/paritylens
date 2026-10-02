/**
 * Form validation with Zod.
 *
 * These check what a person typed, before it is sent, so a mistake is
 * shown next to the field that caused it. They are a convenience for the
 * user. The backend validates everything again and is the authority.
 */
import { z } from "zod";

import { parseJson, stringifyJson } from "./json";

const httpUrl = z
  .string()
  .trim()
  .min(1, "Required.")
  .refine((value) => /^https?:\/\/[^\s/?#]+/.test(value), "Enter an http:// or https:// URL.")
  .refine((value) => !/^https?:\/\/[^/?#]*@/.test(value), "Do not put credentials in the URL.")
  .refine((value) => !/[?#\s]/.test(value), "Leave out any query string or fragment.");

export const projectSchema = z.object({
  name: z.string().trim().min(1, "Required.").max(200),
  description: z.string().max(5000),
  old_base_url: httpUrl,
  new_base_url: httpUrl,
});
export type ProjectForm = z.infer<typeof projectSchema>;

export const METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"] as const;

/** Text that must parse as JSON, or be left empty. */
const optionalJson = z.string().refine((text) => {
  if (text.trim() === "") return true;
  try {
    JSON.parse(text);
    return true;
  } catch {
    return false;
  }
}, "This is not valid JSON.");

// One capture per line:  name = $.path   or   name = $.path (secret)
// The path is only checked for its general form here; the server knows
// the full grammar and reports anything it does not accept.
const CAPTURE_LINE = /^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(\$.*?)(\s+\(secret\))?\s*$/;

const stepSchema = z.object({
  id: z.string().trim().max(200),
  method: z.enum(METHODS),
  path: z
    .string()
    .trim()
    .startsWith("/", "A path starts with /.")
    .refine((value) => !/[?#\s]/.test(value), "No spaces, '?' or '#' in a path."),
  json: optionalJson,
  capture: z.string().refine(
    (text) =>
      text
        .split("\n")
        .filter((line) => line.trim() !== "")
        .every((line) => CAPTURE_LINE.test(line)),
    "One per line, written as name = $.path",
  ),
  // Fields of the stored request that this form does not edit, as JSON.
  rest: z.string(),
});

export const testCaseSchema = z.object({
  name: z.string().trim().min(1, "Required.").max(200),
  noise_detection: z.boolean(),
  enabled: z.boolean(),
  steps: z.array(stepSchema).min(1, "Add at least one step.").max(20),
});
export type TestCaseForm = z.infer<typeof testCaseSchema>;
export type StepForm = z.infer<typeof stepSchema>;

type Capture = { path: string; secret?: boolean };

/** Capture lines into the API's capture object. */
export function parseCapture(text: string): Record<string, Capture> {
  const capture: Record<string, Capture> = {};
  for (const line of text.split("\n")) {
    const match = CAPTURE_LINE.exec(line);
    if (match) {
      capture[match[1]] = { path: match[2], ...(match[3] ? { secret: true } : {}) };
    }
  }
  return capture;
}

/** The API's capture object back into lines. */
export function formatCapture(capture: unknown): string {
  if (typeof capture !== "object" || capture === null) return "";
  return Object.entries(capture as Record<string, string | Capture>)
    .map(([name, value]) => {
      const { path, secret } = typeof value === "string" ? { path: value, secret: false } : value;
      return `${name} = ${path}${secret ? " (secret)" : ""}`;
    })
    .join("\n");
}

type ApiStep = {
  id?: string | null;
  request: { method: string; path: string; json?: unknown } & Record<string, unknown>;
  capture?: unknown;
};

/**
 * A stored step as form values.
 *
 * The form edits the common fields. Anything else a step carries (query,
 * headers, a raw body), set through the API or the CLI, travels through
 * the form untouched in `rest`, so saving from the UI does not drop it.
 *
 * JSON is written with stringifyJson, which keeps numbers exactly as
 * they were stored (see json.ts).
 */
export function stepToForm(step: ApiStep): StepForm {
  const { method, path, json, ...rest } = step.request;
  return {
    id: step.id ?? "",
    method: method as StepForm["method"],
    path,
    json: json == null ? "" : stringifyJson(json, 2),
    capture: formatCapture(step.capture),
    rest: stringifyJson(rest),
  };
}

export function stepFromForm(step: StepForm) {
  const capture = parseCapture(step.capture);
  const rest = step.rest ? (parseJson(step.rest) as Record<string, unknown>) : {};
  return {
    ...(step.id.trim() ? { id: step.id.trim() } : {}),
    request: {
      ...rest,
      method: step.method,
      path: step.path,
      ...(step.json.trim() ? { json: parseJson(step.json) } : {}),
    },
    ...(Object.keys(capture).length > 0 ? { capture } : {}),
  };
}

export const EMPTY_STEP: StepForm = {
  id: "",
  method: "GET",
  path: "/",
  json: "",
  capture: "",
  rest: "",
};

/** A stored test case as form values. Runs on the server, on exact JSON. */
export function testCaseToForm(testCase: {
  name: string;
  noise_detection: boolean;
  enabled: boolean;
  steps: unknown[];
}): TestCaseForm {
  return {
    name: testCase.name,
    noise_detection: testCase.noise_detection,
    enabled: testCase.enabled,
    steps: (testCase.steps as ApiStep[]).map(stepToForm),
  };
}

/** "Name: value" lines into a headers object. */
export function parseHeaders(text: string): Record<string, string> {
  const headers: Record<string, string> = {};
  for (const line of text.split("\n")) {
    const separator = line.indexOf(":");
    if (separator > 0) {
      headers[line.slice(0, separator).trim()] = line.slice(separator + 1).trim();
    }
  }
  return headers;
}

/**
 * Lines that are neither empty nor "Name: value".
 *
 * parseHeaders skips such a line. Saving anyway would silently delete a
 * header someone mistyped, so the form refuses while there are any.
 */
export function invalidHeaderLines(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line !== "" && line.indexOf(":") <= 0);
}

export function formatHeaders(headers: Record<string, string> | undefined): string {
  return Object.entries(headers ?? {})
    .map(([name, value]) => `${name}: ${value}`)
    .join("\n");
}
