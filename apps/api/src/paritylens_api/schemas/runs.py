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


class RunDetail(RunOut):
    rules: RuleSet
    cases: list[CaseResultSummary]


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


class RunDifference(DifferenceOut):
    """A difference with enough context to show it outside its case."""

    case_result_id: uuid.UUID
    case_name: str
    step_id: str


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
