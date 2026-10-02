import { describe, expect, it } from "vitest";

import type { RunSummary } from "./api/types";
import { changeText, formatDateTime, scoreText, severityRank } from "./result";

const summary = (counts: Partial<RunSummary>): RunSummary => ({
  total: 0,
  compatible: 0,
  warning: 0,
  breaking: 0,
  error: 0,
  ...counts,
});

describe("scoreText", () => {
  it("always states what the percentage is a share of", () => {
    expect(scoreText(summary({ total: 50, compatible: 47, breaking: 3 }))).toEqual({
      percent: "94%",
      of: "47 of 50 cases compatible",
    });
  });

  it("leaves cases that could not run out of the denominator", () => {
    // 2 of the 3 that produced a result, not 2 of 5.
    expect(scoreText(summary({ total: 5, compatible: 2, breaking: 1, error: 2 })).of).toBe(
      "2 of 3 cases compatible",
    );
  });

  it("gives no percentage when nothing was evaluated", () => {
    expect(scoreText(summary({ total: 2, error: 2 }))).toEqual({
      percent: "—",
      of: "no case could be evaluated",
    });
  });

  it("rounds down, so 100% means every case", () => {
    expect(scoreText(summary({ total: 1000, compatible: 999, breaking: 1 })).percent).toBe("99%");
  });
});

describe("severityRank", () => {
  it("orders none below low below medium below high below critical", () => {
    const ranks = ["none", "low", "medium", "high", "critical"].map(severityRank);
    expect(ranks).toEqual([0, 1, 2, 3, 4]);
  });
});

describe("changeText", () => {
  it("shows a changed value as old → new, using the exact text from the API", () => {
    expect(changeText({ kind: "value_changed", old_text: "332", new_text: "333" })).toBe(
      "332 → 333",
    );
    expect(changeText({ kind: "type_changed", old_text: '"3"', new_text: "3" })).toBe('"3" → 3');
  });

  it("does not round what JavaScript could not hold", () => {
    // As numbers these would both print as 9007199254740992, and 1.0 as 1.
    expect(
      changeText({ kind: "value_changed", old_text: "9007199254740993", new_text: "9007199254740992" }),
    ).toBe("9007199254740993 → 9007199254740992");
    expect(changeText({ kind: "type_changed", old_text: "1.0", new_text: "1" })).toBe("1.0 → 1");
  });

  it("distinguishes null from absent", () => {
    expect(changeText({ kind: "value_changed", old_text: "null", new_text: '"x"' })).toBe(
      'null → "x"',
    );
    expect(changeText({ kind: "field_added", old_text: "null", new_text: '"JPY"' })).toBe(
      'added "JPY"',
    );
    expect(changeText({ kind: "field_removed", old_text: '{"a": 1}', new_text: "null" })).toBe(
      'removed (was {"a": 1})',
    );
  });

  it("describes array changes with the detail from the engine", () => {
    expect(changeText({ kind: "array_changed", detail: "length 3 → 2" })).toBe("length 3 → 2");
  });
});

describe("formatDateTime", () => {
  it("prints UTC and says so, whatever zone the server runs in", () => {
    expect(formatDateTime("2026-10-02T03:58:00Z")).toBe("2 Oct 2026, 03:58 UTC");
    expect(formatDateTime("2026-10-02T12:58:00+09:00")).toBe("2 Oct 2026, 03:58 UTC");
  });
});
