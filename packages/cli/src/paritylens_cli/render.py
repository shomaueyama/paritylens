"""Printing a RunReport for a person to read in a terminal."""

import json
import re

from paritylens_engine import Difference, DiffKind, NoiseSource, Note, Reason, Severity, Verdict
from paritylens_engine.report import CaseResult, RunReport, StepOutcome, StepResult
from rich.console import Console
from rich.markup import escape

_VERDICT_STYLE = {
    Verdict.COMPATIBLE: ("✓", "green"),
    Verdict.WARNING: ("!", "yellow"),
    Verdict.BREAKING: ("✗", "red"),
    Verdict.ERROR: ("?", "magenta"),
}
_SEVERITY_STYLE = {
    Severity.LOW: "cyan",
    Severity.MEDIUM: "yellow",
    Severity.HIGH: "red",
    Severity.CRITICAL: "bold red",
}
_REASON_TEXT = {
    Reason.CRITICAL_RULE: "marked critical by a rule",
    Reason.CRITICAL_FIELD_NAME: "field name reads like an amount of money",
    Reason.OUTCOME_FLIPPED: "success on one side, failure on the other",
}
_NOISE_TEXT = {
    NoiseSource.RULE: "ignored by a rule",
    NoiseSource.BASELINE: "also changes between two calls to the old API",
    NoiseSource.CLOCK: "the time of the request",
}
_NOTE_TEXT = {
    Note.BODY_NOT_COMPARED_STATUS_CLASS: "bodies not compared: the statuses are of different kinds",
    Note.BODY_NOT_COMPARED_TRUNCATED: "bodies not compared: too large to read in full",
    Note.BASELINE_UNSTABLE: "the old API returned different statuses to the same request",
    Note.BASELINE_UNAVAILABLE: "noise detection unavailable: the repeat request failed",
}
_MAX_VALUE_WIDTH = 60

# C0 and C1 control characters and DEL. Text from an API response is
# printed to a terminal, where these would move the cursor, clear the
# screen, or forge lines of output.
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def printable(text: str) -> str:
    """Make control characters visible instead of letting the terminal act on them."""
    return _CONTROL.sub(lambda match: f"\\x{ord(match.group()):02x}", text)


def _safe(text: str) -> str:
    """Text from a report, made safe to print: no control characters, no markup."""
    return escape(printable(text))


def render_report(report: RunReport, console: Console) -> None:
    console.print(f"old  {_safe(report.old_base_url)}")
    console.print(f"new  {_safe(report.new_base_url)}")
    console.print()
    for case in report.cases:
        _render_case(case, console)
    _render_summary(report, console)


def _render_case(case: CaseResult, console: Console) -> None:
    mark, style = _VERDICT_STYLE[case.verdict]
    label = f"{mark} {case.verdict.value.upper()}"
    console.print(f"[{style}]{label:<13}[/{style}] {_safe(case.name)}")
    for step in case.steps:
        _render_step(step, console, show_id=len(case.steps) > 1)


def _render_step(step: StepResult, console: Console, *, show_id: bool) -> None:
    indent = "    "
    if show_id:
        console.print(f"{indent}[dim]{_safe(step.id)}[/dim]")
        indent += "  "

    if step.outcome is not StepOutcome.COMPARED:
        for side, result in (("old", step.old), ("new", step.new)):
            problem = result.error or result.skipped
            if problem:
                console.print(f"{indent}[magenta]{side}: {_safe(problem)}[/magenta]")
        return
    if step.comparison is None:
        return

    findings = [d for d in step.comparison.differences if d.severity is not Severity.NONE]
    noise = [d for d in step.comparison.differences if d.severity is Severity.NONE]
    for difference in sorted(findings, key=lambda d: -d.severity.rank):
        console.print(indent + _finding_line(difference))
    for note in step.comparison.notes:
        console.print(f"{indent}[dim]note: {_NOTE_TEXT[note]}[/dim]")
    if noise:
        listed = ", ".join(
            f"{_safe(d.path)} ({_NOISE_TEXT[d.noise_source]})" for d in noise if d.noise_source
        )
        console.print(f"{indent}[dim]safe differences: {listed}[/dim]")


def _finding_line(difference: Difference) -> str:
    style = _SEVERITY_STYLE[difference.severity]
    parts = [
        f"[{style}]{difference.severity.value.upper():<8}[/{style}]",
        f"{difference.kind.value:<19}",
        _safe(difference.path),
        " ",
        _change(difference),
    ]
    extra = difference.detail if difference.kind is DiffKind.TYPE_CHANGED else None
    reason = _REASON_TEXT.get(difference.reason)
    remarks = [text for text in (extra, reason) if text]
    if remarks:
        parts.append(f"  [dim]({_safe('; '.join(remarks))})[/dim]")
    return " ".join(parts)


def _change(difference: Difference) -> str:
    old, new = _show(difference.old), _show(difference.new)
    if difference.kind is DiffKind.FIELD_ADDED:
        return f"added {new}"
    if difference.kind is DiffKind.FIELD_REMOVED:
        return f"removed (was {old})"
    if difference.kind is DiffKind.ARRAY_CHANGED and difference.detail:
        return _safe(difference.detail)
    return f"{old} → {new}"


def _show(value: object) -> str:
    text = json.dumps(value, ensure_ascii=False)
    if len(text) > _MAX_VALUE_WIDTH:
        text = text[: _MAX_VALUE_WIDTH - 1] + "…"
    return _safe(text)


def _render_summary(report: RunReport, console: Console) -> None:
    summary = report.summary
    console.print()
    if summary.score is None:
        console.print("[bold]Compatibility[/bold]  not measured (no case could be evaluated)")
    else:
        # The denominator is always shown: 94% of what was tested, not of the API.
        console.print(
            f"[bold]Compatibility[/bold]  {summary.score:.0%}  "
            f"({summary.compatible} of {summary.evaluated} cases)"
        )
    console.print(
        f"breaking {summary.breaking} · warning {summary.warning} · "
        f"compatible {summary.compatible} · error {summary.error}"
    )
