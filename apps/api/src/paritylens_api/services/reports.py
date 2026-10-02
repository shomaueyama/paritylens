"""Storing a RunReport.

One function, used both for runs the worker executed and for reports the
CLI uploads. Whatever produced the report, it lands in the same tables in
the same way.
"""

import uuid
from collections.abc import Sequence
from typing import Any

from paritylens_engine.report import RunReport, SideResult
from sqlalchemy.ext.asyncio import AsyncSession

from paritylens_api.models import CaseResult, Difference, Run, StepResult


def _json(side: SideResult) -> dict[str, Any]:
    return side.model_dump(mode="json", exclude_none=True)


def save_report(
    session: AsyncSession,
    run: Run,
    report: RunReport,
    test_case_ids: Sequence[uuid.UUID | None],
) -> None:
    """Attach a report's results to a run and mark the run completed.

    `test_case_ids` gives, for each case of the report in order, the stored
    test case it came from, or None when there is none (any more).
    """
    run.status = "completed"
    run.engine_version = report.engine_version
    run.started_at = report.started_at
    run.finished_at = report.finished_at
    run.rules_snapshot = report.rules.model_dump(mode="json")
    run.summary = report.summary.model_dump(mode="json")
    run.error = None

    for case_position, case in enumerate(report.cases):
        case_row = CaseResult(
            run=run,
            test_case_id=test_case_ids[case_position],
            position=case_position,
            name=case.name[:200],
            verdict=case.verdict.value,
            max_severity=case.max_severity.value,
        )
        for step_position, step in enumerate(case.steps):
            step_row = StepResult(
                case=case_row,
                position=step_position,
                step_id=step.id[:200],
                outcome=step.outcome.value,
                old=_json(step.old),
                new=_json(step.new),
                notes=[note.value for note in step.comparison.notes] if step.comparison else [],
            )
            for position, difference in enumerate(
                step.comparison.differences if step.comparison else ()
            ):
                step_row.differences.append(
                    Difference(
                        run_id=run.id,
                        position=position,
                        kind=difference.kind.value,
                        path=difference.path,
                        old_value=difference.old,
                        new_value=difference.new,
                        detail=difference.detail,
                        severity=difference.severity.value,
                        reason=difference.reason.value,
                        noise_source=difference.noise_source.value
                        if difference.noise_source
                        else None,
                        hints=[hint.value for hint in difference.hints],
                    )
                )
        session.add(case_row)
