"""Asks a model about a run's findings and stores what it says.

The flow is deliberately one-directional:

    differences (already stored, already judged)
        → findings (a compact summary sent to the model)
        → the model's answer
        → validation (discard anything that is not about a finding we sent)
        → ai_analyses (a separate table)

Nothing flows back. No verdict, severity or score is touched here.
"""

import json
import uuid
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from paritylens_engine import Severity
from pydantic import AfterValidator, BaseModel, ConfigDict, ValidationError
from sqlalchemy import case, delete, func, select, tuple_
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from paritylens_api.ai.prompt import ANALYSIS_SCHEMA, PROMPT_VERSION, SYSTEM_PROMPT
from paritylens_api.ai.provider import LLMError, LLMProvider
from paritylens_api.models import AiAnalysis, CaseResult, Difference, StepResult

# What is sent is bounded on every axis, because every character of it is
# paid for and none of it is under our control: paths come from response
# keys, URLs and case names from whoever wrote the suite.
#
# The model is sent at most this many findings, the most severe first.
MAX_FINDINGS = 60
# Each text in a finding (path, values, detail, URL) is cut to this length.
MAX_VALUE_CHARS = 300
MAX_CASES_PER_FINDING = 5
MAX_CASE_NAME_CHARS = 100
MAX_EXPLANATION_CHARS = 1500

type FindingKey = tuple[str, str]  # (signature, severity)


@dataclass(frozen=True)
class Finding:
    """One distinct difference of a run, as it is described to the model."""

    id: str  # "f1", "f2", ...: short, and meaningless outside this request
    signature: str
    severity: str
    document: dict[str, Any]

    @property
    def key(self) -> FindingKey:
        return (self.signature, self.severity)


def _explanation(value: str) -> str:
    # PostgreSQL text cannot hold NUL, and an explanation of only
    # whitespace explains nothing.
    cleaned = value.replace("\x00", "").strip()
    if not cleaned:
        raise ValueError("empty explanation")
    return cleaned[:MAX_EXPLANATION_CHARS]


class _Analysis(BaseModel):
    model_config = ConfigDict(extra="ignore")

    finding_id: str
    verdict: Literal["safe", "warning", "breaking"]
    confidence: Literal["low", "medium", "high"]
    explanation: Annotated[str, AfterValidator(_explanation)]


class _Answer(BaseModel):
    model_config = ConfigDict(extra="ignore")

    analyses: list[Any]


def _shorten(value: Any, limit: int = MAX_VALUE_CHARS) -> Any:
    if value is None:
        return None
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    if len(text) <= limit:
        return value
    return text[:limit] + "…"


async def collect_findings(session: AsyncSession, run_id: uuid.UUID) -> list[Finding]:
    """The run's distinct findings that are not noise, most severe first.

    A finding is a signature at a severity, the same grouping GET /findings
    uses, described by its first occurrence in run order.

    The grouping and the cut to MAX_FINDINGS happen in the database, and
    of each stored response only the request's method and URL are read.
    Loading rows and grouping them here would bring a whole response body
    into memory once per difference.
    """
    request = StepResult.old["request"]
    occurrences = (
        select(
            Difference.signature,
            Difference.severity,
            Difference.kind,
            Difference.old_value,
            Difference.new_value,
            Difference.detail,
            request["method"].astext.label("method"),
            func.left(request["url"].astext, MAX_VALUE_CHARS + 1).label("url"),
            CaseResult.position.label("case_position"),
            StepResult.position.label("step_position"),
            Difference.position,
        )
        .join(StepResult, Difference.step_result_id == StepResult.id)
        .join(CaseResult, StepResult.case_result_id == CaseResult.id)
        .where(Difference.run_id == run_id, Difference.severity != Severity.NONE.value)
        .ext(distinct_on(Difference.signature, Difference.severity))
        .order_by(
            Difference.signature,
            Difference.severity,
            CaseResult.position,
            StepResult.position,
            Difference.position,
        )
        .subquery()
    )
    rank = case({level.value: level.rank for level in Severity}, value=occurrences.c.severity)
    rows = (
        await session.execute(
            select(occurrences)
            .order_by(
                rank.desc(),
                occurrences.c.case_position,
                occurrences.c.step_position,
                occurrences.c.position,
                occurrences.c.signature,
            )
            .limit(MAX_FINDINGS)
        )
    ).all()
    if not rows:
        return []

    case_names = await _case_names(session, run_id, [(row.signature, row.severity) for row in rows])
    findings = []
    for number, row in enumerate(rows, start=1):
        document = {
            "id": f"f{number}",
            "kind": row.kind,
            "path": _shorten(row.signature.partition(":")[2]),
            "severity": row.severity,
            "old": _shorten(row.old_value),
            "new": _shorten(row.new_value),
            "detail": _shorten(row.detail),
            "request": {"method": row.method, "url": _shorten(row.url)},
            "seen_in_cases": case_names[(row.signature, row.severity)],
        }
        findings.append(Finding(f"f{number}", row.signature, row.severity, document))
    return findings


async def _case_names(
    session: AsyncSession, run_id: uuid.UUID, keys: list[FindingKey]
) -> dict[FindingKey, list[str]]:
    """For each finding, the first few cases it occurs in, in run order."""
    rows = await session.execute(
        select(
            Difference.signature,
            Difference.severity,
            func.left(CaseResult.name, MAX_CASE_NAME_CHARS),
        )
        .join(StepResult, Difference.step_result_id == StepResult.id)
        .join(CaseResult, StepResult.case_result_id == CaseResult.id)
        .where(
            Difference.run_id == run_id,
            tuple_(Difference.signature, Difference.severity).in_(keys),
        )
        .group_by(Difference.signature, Difference.severity, CaseResult.id)
        .order_by(CaseResult.position)
    )
    names: dict[FindingKey, list[str]] = {key: [] for key in keys}
    for signature, severity, name in rows:
        seen = names[(signature, severity)]
        if len(seen) < MAX_CASES_PER_FINDING:
            seen.append(name)
    return names


def validated(answer: dict[str, Any], findings: list[Finding]) -> dict[FindingKey, _Analysis]:
    """Keep only well-formed analyses of findings that were actually sent.

    A model can return an analysis for an ID it invented, the same ID
    twice, or an entry of the wrong shape. Each such entry is dropped on
    its own; the rest of the answer is still used.
    """
    try:
        entries = _Answer.model_validate(answer).analyses
    except ValidationError as exc:
        raise LLMError("the model's answer did not have the expected shape") from exc

    known = {finding.id: finding.key for finding in findings}
    kept: dict[FindingKey, _Analysis] = {}
    for entry in entries:
        try:
            analysis = _Analysis.model_validate(entry)
        except ValidationError:
            continue
        key = known.get(analysis.finding_id)
        if key is None or key in kept:
            continue
        kept[key] = analysis
    return kept


async def request_analysis(
    provider: LLMProvider, findings: list[Finding]
) -> dict[FindingKey, _Analysis]:
    """Ask the model about the findings. Keyed by (signature, severity)."""
    # The findings are sent as one JSON document: data, clearly delimited,
    # with nothing of ours mixed in that the data could be confused with.
    user = json.dumps({"findings": [finding.document for finding in findings]}, ensure_ascii=False)
    answer = await provider.complete_json(system=SYSTEM_PROMPT, user=user, schema=ANALYSIS_SCHEMA)
    return validated(answer, findings)


async def store_analyses(
    session: AsyncSession,
    run_id: uuid.UUID,
    analyses: dict[FindingKey, _Analysis],
    provider: LLMProvider,
) -> None:
    """Replace the run's stored analyses with these."""
    await session.execute(delete(AiAnalysis).where(AiAnalysis.run_id == run_id))
    for (signature, severity), analysis in analyses.items():
        session.add(
            AiAnalysis(
                run_id=run_id,
                signature=signature,
                severity=severity,
                verdict=analysis.verdict,
                confidence=analysis.confidence,
                explanation=analysis.explanation,
                provider=provider.name,
                model=provider.model,
                prompt_version=PROMPT_VERSION,
            )
        )
