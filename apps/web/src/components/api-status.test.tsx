import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ApiStatus } from "./api-status";

describe("ApiStatus", () => {
  it("says the API is up", () => {
    render(<ApiStatus health="up" />);

    expect(screen.getByRole("status")).toHaveTextContent("API is up");
  });

  it("says the API is not reachable", () => {
    render(<ApiStatus health="down" />);

    expect(screen.getByRole("status")).toHaveTextContent("API is not reachable");
  });
});
