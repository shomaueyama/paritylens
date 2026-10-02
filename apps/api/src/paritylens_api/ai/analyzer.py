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
from typing import Any, Literal

from paritylens_engine import Severity
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from paritylens_api.ai.prompt import ANALYSIS_SCHEMA, PROMPT_VERSION, SYSTEM_PROMPT
from paritylens_api.ai.provider import LLMError, LLMProvider
from paritylens_api.models import AiAnalysis, CaseResult, Difference, StepResult

# The model is sent at most this many findings, the most severe first.
MAX_FINDINGS = 60
# Example values are shortened to this many characters.
MAX_VALUE_CHARS = 300
MAX_EXPLANATION_CHARS = 1500


@dataclass(frozen=True)
class Finding:
    """One distinct difference of a run, as it is described to the model."""

    id: str  # "f1", "f2", ...: short, and meaningless outside this request
    signature: str
    document: dict[str, Any]


class _Analysis(BaseModel):
    model_config = ConfigDict(extra="ignore")

    finding_id: str
    verdict: Literal["safe", "warning", "breaking"]
    confidence: Literal["low", "medium", "high"]
    explanation: str = Field(min_length=1)


class _Answer(BaseModel):
    model_config = ConfigDict(extra="ignore")

    analyses: list[Any]


def _shorten(value: Any) -> Any:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    if len(text) <= MAX_VALUE_CHARS:
        return value
    return text[:MAX_VALUE_CHARS] + "…"


async def collect_findings(session: AsyncSession, run_id: uuid.UUID) -> list[Finding]:
    """The run's distinct findings that are not noise, most severe first."""
    rows = await session.execute(
        select(Difference, StepResult.old, CaseResult.name)
        .join(StepResult, Difference.step_result_id == StepResult.id)
        .join(CaseResult, StepResult.case_result_id == CaseResult.id)
        .where(Difference.run_id == run_id, Difference.severity != Severity.NONE.value)
        .order_by(CaseResult.position, StepResult.position, Difference.position)
    )
    by_signature: dict[str, dict[str, Any]] = {}
    for difference, old_side, case_name in rows:
        entry = by_signature.get(difference.signature)
        if entry is None:
            request = old_side.get("request") or {}
            entry = {
                "kind": difference.kind,
                "path": difference.signature.partition(":")[2],
                "severity": difference.severity,
                "old": _shorten(difference.old_value),
                "new": _shorten(difference.new_value),
                "detail": difference.detail,
                "request": {"method": request.get("method"), "url": request.get("url")},
                "seen_in_cases": [],
            }
            by_signature[difference.signature] = entry
        elif Severity(difference.severity).rank > Severity(entry["severity"]).rank:
            entry["severity"] = difference.severity
        if case_name not in entry["seen_in_cases"] and len(entry["seen_in_cases"]) < 5:
            entry["seen_in_cases"].append(case_name)

    ranked = sorted(by_signature.items(), key=lambda item: -Severity(item[1]["severity"]).rank)
    return [
        Finding(id=f"f{number}", signature=signature, document={"id": f"f{number}", **document})
        for number, (signature, document) in enumerate(ranked[:MAX_FINDINGS], start=1)
    ]


def validated(answer: dict[str, Any], findings: list[Finding]) -> dict[str, _Analysis]:
    """Keep only well-formed analyses of findings that were actually sent.

    A model can return an analysis for an ID it invented, the same ID
    twice, or an entry of the wrong shape. Each such entry is dropped on
    its own; the rest of the answer is still used.
    """
    try:
        entries = _Answer.model_validate(answer).analyses
    except ValidationError as exc:
        raise LLMError("the model's answer did not have the expected shape") from exc

    known = {finding.id: finding.signature for finding in findings}
    kept: dict[str, _Analysis] = {}
    for entry in entries:
        try:
            analysis = _Analysis.model_validate(entry)
        except ValidationError:
            continue
        signature = known.get(analysis.finding_id)
        if signature is None or signature in kept:
            continue
        kept[signature] = analysis
    return kept


async def request_analysis(provider: LLMProvider, findings: list[Finding]) -> dict[str, _Analysis]:
    """Ask the model about the findings. Keyed by finding signature."""
    # The findings are sent as one JSON document: data, clearly delimited,
    # with nothing of ours mixed in that the data could be confused with.
    user = json.dumps({"findings": [finding.document for finding in findings]}, ensure_ascii=False)
    answer = await provider.complete_json(system=SYSTEM_PROMPT, user=user, schema=ANALYSIS_SCHEMA)
    return validated(answer, findings)


async def store_analyses(
    session: AsyncSession,
    run_id: uuid.UUID,
    analyses: dict[str, _Analysis],
    provider: LLMProvider,
) -> None:
    """Replace the run's stored analyses with these."""
    await session.execute(delete(AiAnalysis).where(AiAnalysis.run_id == run_id))
    for signature, analysis in analyses.items():
        session.add(
            AiAnalysis(
                run_id=run_id,
                signature=signature,
                verdict=analysis.verdict,
                confidence=analysis.confidence,
                explanation=analysis.explanation.replace("\x00", "")[:MAX_EXPLANATION_CHARS],
                provider=provider.name,
                model=provider.model,
                prompt_version=PROMPT_VERSION,
            )
        )
