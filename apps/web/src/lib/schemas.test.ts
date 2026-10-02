import { describe, expect, it } from "vitest";

import { parseJson, stringifyJson } from "./json";
import {
  formatCapture,
  formatHeaders,
  invalidHeaderLines,
  parseCapture,
  parseHeaders,
  projectSchema,
  stepFromForm,
  stepToForm,
  testCaseSchema,
  testCaseToForm,
} from "./schemas";

const project = {
  name: "Shop",
  description: "",
  old_base_url: "http://a.test",
  new_base_url: "https://b.test",
};

describe("projectSchema", () => {
  it("accepts plain http and https URLs", () => {
    expect(projectSchema.safeParse(project).success).toBe(true);
  });

  it.each([
    ["", "Required."],
    ["ftp://a.test", "Enter an http:// or https:// URL."],
    ["a.test", "Enter an http:// or https:// URL."],
    ["http://user:pass@a.test", "Do not put credentials in the URL."],
    ["http://a.test/?q=1", "Leave out any query string or fragment."],
  ])("rejects %j", (url, message) => {
    const result = projectSchema.safeParse({ ...project, old_base_url: url });

    expect(result.success).toBe(false);
    expect(result.error?.issues[0].message).toBe(message);
  });

  it("requires a name", () => {
    expect(projectSchema.safeParse({ ...project, name: "  " }).success).toBe(false);
  });
});

describe("testCaseSchema", () => {
  const step = { id: "", method: "GET" as const, path: "/orders", json: "", capture: "", rest: "" };
  const testCase = { name: "List", noise_detection: true, enabled: true, steps: [step] };

  it("accepts a minimal case", () => {
    expect(testCaseSchema.safeParse(testCase).success).toBe(true);
  });

  it.each([
    [{ path: "orders" }, "A path starts with /."],
    [{ path: "/orders?x=1" }, "No spaces, '?' or '#' in a path."],
    [{ json: "{not json" }, "This is not valid JSON."],
    [{ capture: "order id = $.id" }, "One per line, written as name = $.path"],
    [{ capture: "order_id: $.id" }, "One per line, written as name = $.path"],
  ])("rejects a step with %j", (override, message) => {
    const result = testCaseSchema.safeParse({ ...testCase, steps: [{ ...step, ...override }] });

    expect(result.error?.issues[0].message).toBe(message);
  });

  it.each(["v = $['first name'].id", "v = $.items[sku=A-100].id", "token = $.token (secret)"])(
    "accepts the capture %j, leaving the path grammar to the server",
    (capture) => {
      const result = testCaseSchema.safeParse({ ...testCase, steps: [{ ...step, capture }] });

      expect(result.success).toBe(true);
    },
  );

  it("needs at least one step", () => {
    expect(testCaseSchema.safeParse({ ...testCase, steps: [] }).success).toBe(false);
  });
});

describe("captures", () => {
  it("round-trip between text and the API's shape, the secret flag included", () => {
    const text = "order_id = $.id\ntoken = $.auth.access_token (secret)";
    const capture = parseCapture(text);

    expect(capture).toEqual({
      order_id: { path: "$.id" },
      token: { path: "$.auth.access_token", secret: true },
    });
    expect(formatCapture(capture)).toBe(text);
  });

  it("keeps an = and spaces inside a path", () => {
    expect(parseCapture("v = $.items[sku=A-100].id")).toEqual({
      v: { path: "$.items[sku=A-100].id" },
    });
    expect(parseCapture("v = $['first name'].id")).toEqual({ v: { path: "$['first name'].id" } });
  });

  it("reads the short form the API also accepts", () => {
    expect(formatCapture({ order_id: "$.id" })).toBe("order_id = $.id");
  });
});

/** A stored step as the edit page receives it: parsed without rounding. */
const stored = (text: string) => parseJson(text) as Parameters<typeof stepToForm>[0];

describe("steps", () => {
  it("come back from the form exactly as they were stored", () => {
    // Everything a step can carry: a secret capture, fields the form does
    // not edit, and numbers JavaScript cannot represent.
    const text =
      '{"id":"login","request":{"method":"POST","path":"/login",' +
      '"query":{"tenant":"acme"},"headers":{"X-Trace":"1"},' +
      '"json":{"id":9007199254740993,"amount":1.0}},' +
      '"capture":{"token":{"path":"$.token","secret":true},"user":{"path":"$.user.id"}}}';

    const saved = stepFromForm(stepToForm(stored(text)));

    expect(parseJson(stringifyJson(saved))).toEqual(parseJson(text));
    expect(stringifyJson(saved)).toContain("9007199254740993");
    expect(stringifyJson(saved)).toContain("1.0");
    expect(stringifyJson(saved)).toContain('"secret":true');
  });

  it("carry fields the form does not edit through an edit of another field", () => {
    const step = stored(
      '{"request":{"method":"GET","path":"/orders","query":{"status":"open"},"body":"raw"}}',
    );

    const edited = { ...stepToForm(step), path: "/orders/all" };

    expect(stringifyJson(stepFromForm(edited).request)).toBe(
      '{"query":{"status":"open"},"body":"raw","method":"GET","path":"/orders/all"}',
    );
  });

  it.each(["0", "false", '""', "[]"])("keep a JSON body of %s", (json) => {
    const step = stored(`{"request":{"method":"POST","path":"/","json":${json}}}`);

    expect(stringifyJson(stepFromForm(stepToForm(step)).request)).toContain(`"json":${json}`);
  });

  it("leave out what is empty", () => {
    const form = stepToForm(stored('{"request":{"method":"GET","path":"/"}}'));

    expect(stringifyJson(stepFromForm(form))).toBe('{"request":{"method":"GET","path":"/"}}');
  });
});

describe("testCaseToForm", () => {
  it("turns a stored test case into plain strings the form can hold", () => {
    const values = testCaseToForm(
      parseJson(
        '{"name":"Create","noise_detection":false,"enabled":true,' +
          '"steps":[{"request":{"method":"POST","path":"/orders","json":{"n":1.0}}}]}',
      ) as Parameters<typeof testCaseToForm>[0],
    );

    expect(values.name).toBe("Create");
    expect(values.noise_detection).toBe(false);
    expect(values.steps[0].json).toBe('{\n  "n": 1.0\n}');
    // Only strings and booleans: safe to hand from the server to the browser.
    expect(JSON.parse(JSON.stringify(values))).toEqual(values);
  });
});

describe("headers", () => {
  it("round-trip between lines and an object", () => {
    const text = "Authorization: Bearer {{secret.TOKEN}}\nX-Tenant: acme";

    expect(parseHeaders(text)).toEqual({
      Authorization: "Bearer {{secret.TOKEN}}",
      "X-Tenant": "acme",
    });
    expect(formatHeaders(parseHeaders(text))).toBe(text);
  });

  it("keeps colons in the value", () => {
    expect(parseHeaders("X-Url: http://a.test")).toEqual({ "X-Url": "http://a.test" });
  });

  it("reports lines that are not headers, so the form can refuse to save", () => {
    const text = "X-Keep: 1\nAuthorization Bearer {{secret.T}}\n\n: no name\n";

    expect(invalidHeaderLines(text)).toEqual(["Authorization Bearer {{secret.T}}", ": no name"]);
    expect(invalidHeaderLines("X-Keep: 1\n\n")).toEqual([]);
  });
});
