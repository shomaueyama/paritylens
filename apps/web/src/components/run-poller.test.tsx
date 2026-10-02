import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { isSettled, RunPoller } from "./run-poller";

const router = { refresh: vi.fn() };
vi.mock("next/navigation", () => ({ useRouter: () => router }));

const get = vi.fn();
vi.mock("@/lib/api/client", () => ({ api: { GET: (...args: unknown[]) => get(...args) } }));

function renderPoller(status: string, aiStatus = "none") {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <RunPoller runId="run-1" status={status} aiStatus={aiStatus} />
    </QueryClientProvider>,
  );
}

const answer = (status: number, run?: { status: string; ai_status: string }) => ({
  data: run,
  response: new Response(null, { status }),
});

describe("isSettled", () => {
  it.each([
    ["queued", "none", false],
    ["running", "none", false],
    ["completed", "none", true],
    ["completed", "pending", false],
    ["completed", "running", false],
    ["completed", "completed", true],
    ["completed", "failed", true],
    ["failed", "none", true],
  ])("run %s with analysis %s → %s", (status, aiStatus, settled) => {
    expect(isSettled({ status, aiStatus })).toBe(settled);
  });
});

describe("RunPoller", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("says what is happening while the run is not done", () => {
    get.mockResolvedValue(answer(200, { status: "queued", ai_status: "none" }));

    renderPoller("queued");

    expect(screen.getByRole("status")).toHaveTextContent("Waiting for a worker");
  });

  it("keeps watching a finished run while its AI analysis is under way", () => {
    get.mockResolvedValue(answer(200, { status: "completed", ai_status: "running" }));

    renderPoller("completed", "running");

    expect(screen.getByRole("status")).toHaveTextContent("AI analysis in progress");
  });

  it("shows nothing and asks nothing once everything has settled", async () => {
    renderPoller("completed", "completed");

    expect(screen.queryByRole("status")).toBeNull();
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(get).not.toHaveBeenCalled();
  });

  it("reloads the page when the run finishes", async () => {
    get.mockResolvedValue(answer(200, { status: "completed", ai_status: "none" }));

    renderPoller("running");

    await vi.waitFor(() => expect(router.refresh).toHaveBeenCalled(), { timeout: 4000 });
  });

  it.each([404, 401])(
    "stops and reloads when the run is gone or the session has ended (%i)",
    async (status) => {
      get.mockResolvedValue(answer(status));

      renderPoller("running");

      await vi.waitFor(() => expect(router.refresh).toHaveBeenCalled(), { timeout: 4000 });
      const calls = get.mock.calls.length;
      // No further requests: it does not treat the error as "still running".
      await new Promise((resolve) => setTimeout(resolve, 1800));
      expect(get.mock.calls.length).toBe(calls);
    },
    10_000,
  );
});
