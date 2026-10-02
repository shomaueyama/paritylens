import { afterEach, describe, expect, it, vi } from "vitest";

import { getApiHealth } from "./api-health";

describe("getApiHealth", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("reports up when the API answers 200", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 200 })));

    await expect(getApiHealth()).resolves.toBe("up");
  });

  it("reports down when the API answers an error status", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 503 })));

    await expect(getApiHealth()).resolves.toBe("down");
  });

  it("reports down when the API cannot be reached", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("fetch failed")));

    await expect(getApiHealth()).resolves.toBe("down");
  });
});
