import { afterEach, describe, expect, it, vi } from "vitest";

import { problemMessage, send } from "./client";

const answer = (status: number, body?: unknown) => ({
  response: new Response(null, { status }),
  ...(status < 400 ? { data: body } : { error: body }),
});

describe("send", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns the data of a successful call", async () => {
    await expect(send(Promise.resolve(answer(200, { id: "p-1" })))).resolves.toEqual({ id: "p-1" });
  });

  it("returns undefined for a success with no content", async () => {
    await expect(send(Promise.resolve(answer(204)))).resolves.toBeUndefined();
  });

  it("throws the server's explanation", async () => {
    const problem = { title: "Unprocessable Content", detail: "secrets not set: SHOP_TOKEN" };

    await expect(send(Promise.resolve(answer(422, problem)))).rejects.toThrow(
      "secrets not set: SHOP_TOKEN",
    );
  });

  it("treats an error status as an error even when it has no body", async () => {
    // A gateway answering 502 with nothing. `error` is undefined here,
    // and checking only that would call this a success.
    await expect(send(Promise.resolve(answer(502)))).rejects.toThrow("The server answered 502.");
  });

  it("explains a request that never got an answer", async () => {
    await expect(send(Promise.reject(new TypeError("Failed to fetch")))).rejects.toThrow(
      "Could not reach the server.",
    );
  });

  it("sends the browser to the login page when the session has ended", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { assign });

    await expect(send(Promise.resolve(answer(401, { title: "Unauthorized" })))).rejects.toThrow(
      "Your session has ended.",
    );
    expect(assign).toHaveBeenCalledWith("/login");
  });
});

describe("problemMessage", () => {
  it("prefers the first field error, then the detail, then the title", () => {
    expect(
      problemMessage({ detail: "invalid", errors: [{ location: "body.name", message: "too short" }] }),
    ).toBe("body.name: too short");
    expect(problemMessage({ title: "Conflict", detail: "already registered" })).toBe(
      "already registered",
    );
    expect(problemMessage({ title: "Conflict" })).toBe("Conflict");
    expect(problemMessage(undefined, "fallback")).toBe("fallback");
  });
});
