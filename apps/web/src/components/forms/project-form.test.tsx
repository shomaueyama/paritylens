import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProjectForm } from "./project-form";

// The form talks to two things outside itself: the router and the API.
// Both are replaced, so the test is about the form alone.
const router = { push: vi.fn(), refresh: vi.fn() };
vi.mock("next/navigation", () => ({ useRouter: () => router }));

const post = vi.fn();
vi.mock("@/lib/api/client", async (original) => ({
  ...(await original<typeof import("@/lib/api/client")>()),
  api: { POST: (...args: unknown[]) => post(...args), PATCH: vi.fn() },
}));

async function fill(label: string, value: string) {
  await userEvent.type(screen.getByLabelText(label), value);
}

describe("ProjectForm", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows each mistake next to its field and sends nothing", async () => {
    render(<ProjectForm />);
    await fill("Old API base URL", "legacy.example.com");

    await userEvent.click(screen.getByRole("button", { name: "Create project" }));

    expect(await screen.findAllByRole("alert")).toHaveLength(3);
    expect(screen.getByLabelText("Name")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText("Enter an http:// or https:// URL.")).toBeInTheDocument();
    expect(post).not.toHaveBeenCalled();
  });

  it("creates the project and goes to it", async () => {
    post.mockResolvedValue({ data: { id: "p-1" }, response: new Response(null, { status: 201 }) });
    render(<ProjectForm />);
    await fill("Name", "Shop API migration");
    await fill("Old API base URL", "http://legacy.test");
    await fill("New API base URL", "http://modern.test");

    await userEvent.click(screen.getByRole("button", { name: "Create project" }));

    await vi.waitFor(() => expect(router.push).toHaveBeenCalledWith("/projects/p-1"));
    expect(post).toHaveBeenCalledWith("/api/v1/projects", {
      body: {
        name: "Shop API migration",
        description: "",
        old_base_url: "http://legacy.test",
        new_base_url: "http://modern.test",
      },
    });
  });

  it("shows what the server says when it refuses", async () => {
    post.mockResolvedValue({
      error: { detail: "this deployment cannot call that URL: port 8080 is not allowed" },
      response: new Response(null, { status: 422 }),
    });
    render(<ProjectForm />);
    await fill("Name", "Shop");
    await fill("Old API base URL", "http://legacy.test:8080");
    await fill("New API base URL", "http://modern.test");

    await userEvent.click(screen.getByRole("button", { name: "Create project" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("port 8080 is not allowed");
    expect(router.push).not.toHaveBeenCalled();
  });

  async function fillValidProject() {
    await fill("Name", "Shop");
    await fill("Old API base URL", "http://legacy.test");
    await fill("New API base URL", "http://modern.test");
  }

  it("says so when the request never reached the server", async () => {
    post.mockRejectedValue(new TypeError("Failed to fetch"));
    render(<ProjectForm />);
    await fillValidProject();

    await userEvent.click(screen.getByRole("button", { name: "Create project" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not reach the server.");
    // And the form can be submitted again.
    expect(screen.getByRole("button", { name: "Create project" })).toBeEnabled();
  });

  it("does not mistake an error without a body for success", async () => {
    post.mockResolvedValue({ response: new Response(null, { status: 502 }) });
    render(<ProjectForm />);
    await fillValidProject();

    await userEvent.click(screen.getByRole("button", { name: "Create project" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("The server answered 502.");
    expect(router.push).not.toHaveBeenCalled();
  });

  it("stays disabled after success, so a second click cannot create a second project", async () => {
    post.mockResolvedValue({ data: { id: "p-1" }, response: new Response(null, { status: 201 }) });
    render(<ProjectForm />);
    await fillValidProject();

    await userEvent.click(screen.getByRole("button", { name: "Create project" }));

    await vi.waitFor(() => expect(router.push).toHaveBeenCalled());
    expect(screen.getByRole("button", { name: "Create project" })).toBeDisabled();
  });
});
