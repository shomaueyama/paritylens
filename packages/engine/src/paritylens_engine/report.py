"""RunReport: the complete, self-contained record of one run.

This is the contract between whatever executed the run (the CLI on a
user's machine, or the hosted worker) and whatever stores and shows it.
Both produce exactly this, so there is one code path for saving results.

A report never contains credentials. Requests and responses are redacted
before they are put into one.
"""

from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from paritylens_engine.model import (
    ResponseSnapshot,
    RuleSet,
    RunSummary,
    Severity,
    StepComparison,
    Verdict,
)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RequestSnapshot(_Frozen):
    method: str
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    body: str | None = None


class SideResult(_Frozen):
    """What happened when one step was sent to one API.

    Exactly one of three things: a response came back, the request failed
    (`error`), or it was never sent (`skipped`).
    """

    request: RequestSnapshot | None = None
    response: ResponseSnapshot | None = None
    error: str | None = None
    skipped: str | None = None


class StepOutcome(StrEnum):
    # Both sides answered and the answers were compared.
    COMPARED = "compared"
    # A request failed on at least one side.
    ERROR = "error"
    # The step could not be sent on at least one side, usually because an
    # earlier step did not return the value this one needs.
    SKIPPED = "skipped"


class StepResult(_Frozen):
    id: str
    outcome: StepOutcome
    old: SideResult
    new: SideResult
    comparison: StepComparison | None = None


class CaseResult(_Frozen):
    name: str
    verdict: Verdict
    max_severity: Severity
    steps: tuple[StepResult, ...]


class RunReport(_Frozen):
    schema_version: Literal[1] = 1
    engine_version: str
    started_at: AwareDatetime
    finished_at: AwareDatetime
    old_base_url: str
    new_base_url: str
    # The rules in force, so the result can be understood later even if
    # the project's rules have changed since.
    rules: RuleSet
    summary: RunSummary
    cases: tuple[CaseResult, ...]
