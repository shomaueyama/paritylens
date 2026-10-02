"""Checking a report that arrives from outside before it is stored.

A report uploaded by the CLI is input like any other. It has the right
shape (the RunReport model saw to that), but its contents are whatever
the sender wrote. Stored unchecked, a report could claim a million
passing cases it does not contain, or hold values the database rejects.
"""

from datetime import UTC, datetime

from paritylens_engine.model import MAX_DIFFERENCES_PER_STEP, Severity, Verdict
from paritylens_engine.report import CaseResult, RunReport
from paritylens_engine.suite import MAX_CASES_PER_SUITE, MAX_STEPS_PER_CASE
from paritylens_engine.verdict import summarize, verdict_for

from paritylens_api.core.errors import InvalidRequestError
from paritylens_api.schemas.common import reject_unstorable

_EARLIEST = datetime(2000, 1, 1, tzinfo=UTC)
_LATEST = datetime(2100, 1, 1, tzinfo=UTC)
MAX_NAME_CHARS = 200
MAX_VERSION_CHARS = 20


def checked(report: RunReport) -> RunReport:
    """The report with its totals recomputed, or InvalidRequestError."""
    try:
        reject_unstorable(report.model_dump(mode="json"))
    except ValueError as exc:
        raise InvalidRequestError(f"the report cannot be stored: {exc}") from exc

    if len(report.engine_version) > MAX_VERSION_CHARS:
        raise InvalidRequestError("engine_version is too long")
    if not (_EARLIEST <= report.started_at <= report.finished_at <= _LATEST):
        raise InvalidRequestError("started_at and finished_at are not a plausible time span")
    if len(report.cases) > MAX_CASES_PER_SUITE:
        raise InvalidRequestError(f"a report may hold at most {MAX_CASES_PER_SUITE} cases")

    cases = tuple(_checked_case(case) for case in report.cases)
    # The summary is derived from the cases, never taken on trust.
    return report.model_copy(
        update={"cases": cases, "summary": summarize(case.verdict for case in cases)}
    )


def _checked_case(case: CaseResult) -> CaseResult:
    if len(case.name) > MAX_NAME_CHARS:
        raise InvalidRequestError("a case name is too long")
    if len(case.steps) > MAX_STEPS_PER_CASE:
        raise InvalidRequestError(f"a case may hold at most {MAX_STEPS_PER_CASE} steps")

    max_severity = Severity.NONE
    for step in case.steps:
        if len(step.id) > MAX_NAME_CHARS:
            raise InvalidRequestError("a step id is too long")
        if step.comparison is None:
            continue
        if len(step.comparison.differences) > MAX_DIFFERENCES_PER_STEP:
            raise InvalidRequestError(
                f"a step may hold at most {MAX_DIFFERENCES_PER_STEP} differences"
            )
        if step.comparison.max_severity.rank > max_severity.rank:
            max_severity = step.comparison.max_severity

    # A verdict may be more cautious than its differences call for (a body
    # too large to compare is a warning), but never less.
    least = verdict_for(max_severity)
    acceptable = {
        Verdict.COMPATIBLE: {Verdict.COMPATIBLE, Verdict.WARNING, Verdict.ERROR},
        Verdict.WARNING: {Verdict.WARNING, Verdict.ERROR},
        Verdict.BREAKING: {Verdict.BREAKING, Verdict.ERROR},
    }[least]
    if case.verdict not in acceptable:
        raise InvalidRequestError(
            f"case {case.name!r} is marked {case.verdict.value} "
            f"but holds a difference of severity {max_severity.value}"
        )
    return case.model_copy(update={"max_severity": max_severity})
