import uuid
from datetime import datetime
from typing import Literal

from paritylens_engine.model import (
    DiffKind,
    Hint,
    NoiseSource,
    Note,
    Reason,
    RuleSet,
    RunSummary,
    Severity,
    Verdict,
)
from paritylens_engine.report import SideResult, StepOutcome
from pydantic import JsonValue

from paritylens_api.schemas.common import ApiModel


class RunOut(ApiModel):
    id: uuid.UUID
    project_id: uuid.UUID
    source: Literal["hosted", "cli"]
    status: Literal["queued", "running", "completed", "failed"]
    ai_status: Literal["none", "pending", "running", "completed", "failed", "skipped"]
    old_base_url: str
    new_base_url: str
    summary: RunSummary | None
    engine_version: str | None
    error: str | None
    ai_error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class RunPage(ApiModel):
    runs: list[RunOut]
    # Pass as `before` to get the next page; null when there is none.
    next_cursor: str | None


class CaseResultSummary(ApiModel):
    id: uuid.UUID
    test_case_id: uuid.UUID | None
    position: int
    name: str
    verdict: Verdict
    max_severity: Severity


class AnalysisOut(ApiModel):
    """A language model's opinion about one finding. Advisory: it changes no verdict."""

    # Matches DifferenceOut.signature.
    signature: str
    verdict: Literal["safe", "warning", "breaking"]
    confidence: Literal["low", "medium", "high"]
    explanation: str
    provider: str
    model: str


class RunDetail(RunOut):
    rules: RuleSet
    cases: list[CaseResultSummary]
    analyses: list[AnalysisOut]


class DifferenceOut(ApiModel):
    id: uuid.UUID
    kind: DiffKind
    path: str
    old_value: JsonValue
    new_value: JsonValue
    detail: str | None
    severity: Severity
    reason: Reason
    noise_source: NoiseSource | None
    hints: list[Hint]
    # The two values as JSON text, exactly as stored. A browser reading
    # old_value/new_value as numbers would round 9007199254740993 and turn
    # 1.0 into 1; these are for display and survive that.
    old_text: str = ""
    new_text: str = ""
    # Shared by the same finding wherever it occurs in the run.
    signature: str
    # The path as a rule pattern covering every array position, or null
    # when the difference is not inside a JSON body.
    pattern: str | None = None


class RunDifference(DifferenceOut):
    """A difference with enough context to show it outside its case."""

    case_result_id: uuid.UUID
    case_name: str
    step_id: str


class FindingCase(ApiModel):
    id: uuid.UUID
    name: str


class Finding(ApiModel):
    """One distinct difference of a run: the same change, wherever it was seen.

    A field whose type changed shows up in every case that returns it.
    Grouping is done by the database, so a run with a hundred thousand
    differences still yields a short list.
    """

    signature: str
    severity: Severity
    kind: DiffKind
    # The path with array positions generalised; a rule pattern when
    # `is_body_path` is true.
    path: str
    is_body_path: bool
    count: int
    # One member of the group, to show what the change looks like.
    example: DifferenceOut
    case_count: int
    # The first few cases it occurred in, in run order.
    cases: list[FindingCase]


class RunFindings(ApiModel):
    findings: list[Finding]
    # True when there were more distinct findings than are listed.
    truncated: bool


class StepResultOut(ApiModel):
    id: uuid.UUID
    position: int
    step_id: str
    outcome: StepOutcome
    old: SideResult
    new: SideResult
    notes: list[Note]
    differences: list[DifferenceOut]


class CaseResultDetail(CaseResultSummary):
    run_id: uuid.UUID
    steps: list[StepResultOut]
