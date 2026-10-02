import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Analysis, Difference, Finding } from "@/lib/api/types";

import { SeverityBadge, VerdictBadge } from "./badges";
import { AiOpinion, DifferencesTable, FindingsList } from "./differences-table";
import { Score, SummaryCounts } from "./score";

const difference = (overrides: Partial<Difference> = {}): Difference => ({
  id: "d-1",
  kind: "value_changed",
  path: "$.total",
  old_value: 332,
  new_value: 333,
  old_text: "332",
  new_text: "333",
  detail: null,
  severity: "critical",
  reason: "critical_field_name",
  noise_source: null,
  hints: [],
  signature: "value_changed:$.total",
  pattern: "$.total",
  ...overrides,
});

const finding = (overrides: Partial<Finding> = {}): Finding => ({
  signature: "type_changed:$.items[*].quantity",
  severity: "high",
  kind: "type_changed",
  path: "$.items[*].quantity",
  is_body_path: true,
  count: 5,
  example: difference({
    kind: "type_changed",
    path: "$.items[0].quantity",
    old_text: '"3"',
    new_text: "3",
    severity: "high",
    reason: "default_for_kind",
  }),
  case_count: 2,
  cases: [
    { id: "case-1", name: "One line" },
    { id: "case-2", name: "Two lines" },
  ],
  ...overrides,
});

const analysis: Analysis = {
  signature: "type_changed:$.items[*].quantity",
  verdict: "breaking",
  confidence: "high",
  explanation: "Clients that parse quantity as a string will fail.",
  provider: "anthropic",
  model: "claude-opus-5-5",
};

describe("badges", () => {
  it("show the severity and the verdict as text, not only as colour", () => {
    render(
      <>
        <SeverityBadge severity="critical" />
        <VerdictBadge verdict="breaking" />
      </>,
    );

    expect(screen.getByText("critical")).toBeInTheDocument();
    expect(screen.getByText("breaking")).toBeInTheDocument();
  });

  it("do not break on a value they do not know", () => {
    render(<SeverityBadge severity="future-level" />);

    expect(screen.getByText("future-level")).toBeInTheDocument();
  });
});

describe("Score", () => {
  it("never shows the percentage without its denominator", () => {
    render(<Score summary={{ total: 8, compatible: 1, warning: 0, breaking: 7, error: 0 }} />);

    expect(screen.getByText("12%")).toBeInTheDocument();
    expect(screen.getByText("1 of 8 cases compatible")).toBeInTheDocument();
  });

  it("says so when nothing could be evaluated", () => {
    render(<Score summary={{ total: 2, compatible: 0, warning: 0, breaking: 0, error: 2 }} />);

    expect(screen.getByText("no case could be evaluated")).toBeInTheDocument();
  });
});

describe("SummaryCounts", () => {
  it("lists every verdict with its count", () => {
    render(
      <SummaryCounts summary={{ total: 9, compatible: 1, warning: 2, breaking: 5, error: 1 }} />,
    );

    const expected = { breaking: "5", warning: "2", compatible: "1", error: "1" };
    for (const [label, count] of Object.entries(expected)) {
      const term = screen.getByText(label);
      expect(within(term.parentElement as HTMLElement).getByText(count)).toBeInTheDocument();
    }
  });
});

describe("DifferencesTable", () => {
  it("shows what changed, how badly, and why it is rated that way", () => {
    render(<DifferencesTable differences={[difference()]} />);

    expect(screen.getByText("critical")).toBeInTheDocument();
    expect(screen.getByText("$.total")).toBeInTheDocument();
    expect(screen.getByText("332 → 333")).toBeInTheDocument();
    expect(screen.getByText("The field name reads like an amount of money.")).toBeInTheDocument();
  });

  it("renders a response value as text, never as markup", () => {
    const hostile = difference({ new_text: '"<img src=x onerror=\\"alert(1)\\">"' });

    const { container } = render(<DifferencesTable differences={[hostile]} />);

    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText(/onerror/)).toBeInTheDocument();
  });

  it("renders the per-row action when one is given", () => {
    render(
      <DifferencesTable
        differences={[difference()]}
        action={(row) => <button>ignore {row.pattern}</button>}
      />,
    );

    expect(screen.getByRole("button", { name: "ignore $.total" })).toBeInTheDocument();
  });
});

describe("FindingsList", () => {
  it("shows a finding once, with the cases it was seen in", () => {
    render(<FindingsList findings={[finding()]} runId="run-1" />);

    expect(screen.getAllByText("$.items[*].quantity")).toHaveLength(1);
    expect(screen.getByText('"3" → 3')).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "One line" })).toHaveAttribute(
      "href",
      "/runs/run-1/cases/case-1",
    );
    expect(screen.getByRole("link", { name: "Two lines" })).toHaveAttribute(
      "href",
      "/runs/run-1/cases/case-2",
    );
  });

  it("says how many more cases there are than it lists", () => {
    render(<FindingsList findings={[finding({ case_count: 14 })]} runId="run-1" />);

    expect(screen.getByText(/and 12 more/)).toBeInTheDocument();
  });

  it("puts the AI opinion next to its finding and nowhere else", () => {
    const other = finding({
      signature: "field_added:$.currency",
      path: "$.currency",
      kind: "field_added",
      severity: "low",
    });

    render(
      <FindingsList
        findings={[finding(), other]}
        runId="run-1"
        analyses={{ [analysis.signature]: analysis }}
      />,
    );

    expect(screen.getAllByText(/AI opinion/)).toHaveLength(1);
    const item = screen.getByText("$.items[*].quantity").closest("li") as HTMLElement;
    expect(within(item).getByText(analysis.explanation)).toBeInTheDocument();
  });
});

describe("AiOpinion", () => {
  it("is labelled as an opinion, with the model that gave it", () => {
    render(
      <>
        <SeverityBadge severity="high" />
        <AiOpinion analysis={{ ...analysis, verdict: "safe" }} />
      </>,
    );

    // The deterministic severity and the model's verdict are both on
    // screen, and they are allowed to disagree.
    expect(screen.getByText("high")).toBeInTheDocument();
    expect(screen.getByText("safe")).toBeInTheDocument();
    expect(screen.getByText(/AI opinion/)).toHaveTextContent("claude-opus-5-5");
  });
});
