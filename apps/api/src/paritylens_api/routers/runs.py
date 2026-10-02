"""Runs: starting one, uploading one, and reading results."""

import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Query
from paritylens_engine import Severity
from paritylens_engine.model import RuleSet
from paritylens_engine.report import RunReport
from pydantic import ValidationError
from sqlalchemy import case, func, select, tuple_
from sqlalchemy.orm import selectinload

from paritylens_api.core.errors import InvalidRequestError, TooManyRequestsError
from paritylens_api.deps import PrincipalDep, SessionDep, SettingsDep
from paritylens_api.models import (
    CaseResult,
    Difference,
    Project,
    Rule,
    Run,
    Secret,
    StepResult,
    TestCase,
    Workspace,
)
from paritylens_api.repositories.owned import (
    get_case_result,
    get_child,
    get_project,
    list_children,
)
from paritylens_api.schemas.runs import (
    CaseResultDetail,
    CaseResultSummary,
    RunDetail,
    RunDifference,
    RunOut,
    RunPage,
)
from paritylens_api.services.egress import check_targets
from paritylens_api.services.report_import import checked
from paritylens_api.services.reports import save_report
from paritylens_api.services.suites import referenced_secrets, suite_snapshot

router = APIRouter(tags=["runs"])


@router.post("/projects/{project_id}/runs", status_code=202)
async def start_run(
    project_id: uuid.UUID, principal: PrincipalDep, session: SessionDep, settings: SettingsDep
) -> RunOut:
    """Queue a run of the project's enabled test cases. A worker picks it up.

    202 Accepted: the request was taken, the work is not done yet. Poll
    GET /runs/{id} for the result.
    """
    project = await get_project(session, principal.workspace_id, project_id)
    cases = await list_children(session, TestCase, principal.workspace_id, project_id)
    rules = await list_children(session, Rule, principal.workspace_id, project_id)
    check_targets(settings, project.old_base_url, project.new_base_url)
    try:
        snapshot = suite_snapshot(project, cases, rules)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        raise InvalidRequestError(f"the project cannot be run as configured: {problems}") from exc

    stored = set(await session.scalars(select(Secret.name).where(Secret.project_id == project.id)))
    missing = referenced_secrets(snapshot) - stored
    if missing:
        raise InvalidRequestError(f"secrets not set: {', '.join(sorted(missing))}")

    # A cap per workspace, so one tenant cannot fill the queue. The
    # workspace row is locked first: without that, requests arriving
    # together would each count before any of them had inserted.
    await session.execute(
        select(Workspace.id).where(Workspace.id == principal.workspace_id).with_for_update()
    )
    in_flight = await session.scalar(
        select(func.count())
        .select_from(Run)
        .join(Project, Run.project_id == Project.id)
        .where(
            Project.workspace_id == principal.workspace_id,
            Run.status.in_(("queued", "running")),
        )
    )
    if (in_flight or 0) >= settings.max_queued_runs_per_workspace:
        raise TooManyRequestsError("too many runs are already queued; wait for one to finish")

    run = Run(
        project_id=project.id,
        created_by=principal.user_id,
        source="hosted",
        status="queued",
        old_base_url=project.old_base_url,
        new_base_url=project.new_base_url,
        rules_snapshot=snapshot["suite"]["rules"],
        suite_snapshot=snapshot,
    )
    session.add(run)
    await session.flush()
    await session.refresh(run)
    return RunOut.model_validate(run)


@router.post("/projects/{project_id}/runs/import", status_code=201)
async def import_run(
    project_id: uuid.UUID, report: RunReport, principal: PrincipalDep, session: SessionDep
) -> RunOut:
    """Store a report produced elsewhere, e.g. by `paritylens run --upload`."""
    project = await get_project(session, principal.workspace_id, project_id)
    report = checked(report)
    cases = await list_children(session, TestCase, principal.workspace_id, project_id)
    # Link a result to a stored test case by name, where the name is
    # unambiguous. A report from the CLI carries no IDs.
    names = Counter(case.name for case in cases)
    by_name = {case.name: case.id for case in cases if names[case.name] == 1}
    run = Run(
        project_id=project.id,
        created_by=principal.user_id,
        source="cli",
        status="completed",
        old_base_url=report.old_base_url[:2000],
        new_base_url=report.new_base_url[:2000],
    )
    session.add(run)
    await session.flush()
    save_report(session, run, report, [by_name.get(case.name) for case in report.cases])
    await session.flush()
    await session.refresh(run)
    return RunOut.model_validate(run)


_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _encode_cursor(run: Run) -> str:
    # Microseconds since the epoch and the ID: digits, hyphens and one
    # underscore, so the cursor needs no escaping in a query string.
    # Integer arithmetic throughout: a float would round the last digit
    # and the page boundary would land on the wrong row.
    micros = (run.created_at - _EPOCH) // timedelta(microseconds=1)
    return f"{micros}_{run.id}"


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        micros, _, run_id = cursor.partition("_")
        created_at = _EPOCH + timedelta(microseconds=int(micros))
        return created_at, uuid.UUID(run_id)
    except (ValueError, OverflowError) as exc:
        raise InvalidRequestError("the cursor is not valid") from exc


@router.get("/projects/{project_id}/runs")
async def list_runs(
    project_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    before: str | None = None,
) -> RunPage:
    """Newest first. Paged by cursor, so a page stays stable while new runs arrive."""
    await get_project(session, principal.workspace_id, project_id)
    query = select(Run).where(Run.project_id == project_id)
    if before is not None:
        query = query.where(tuple_(Run.created_at, Run.id) < _decode_cursor(before))
    # One more than asked for: its presence says there is a next page.
    rows = list(
        await session.scalars(query.order_by(Run.created_at.desc(), Run.id.desc()).limit(limit + 1))
    )
    page, more = rows[:limit], len(rows) > limit
    cursor = _encode_cursor(page[-1]) if more else None
    return RunPage(runs=[RunOut.model_validate(row) for row in page], next_cursor=cursor)


@router.get("/runs/{run_id}")
async def read_run(run_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> RunDetail:
    run = await get_child(session, Run, principal.workspace_id, run_id)
    cases = await session.scalars(
        select(CaseResult).where(CaseResult.run_id == run.id).order_by(CaseResult.position)
    )
    return RunDetail(
        **RunOut.model_validate(run).model_dump(),
        rules=RuleSet.model_validate(run.rules_snapshot or {}),
        cases=[CaseResultSummary.model_validate(case) for case in cases],
    )


@router.get("/runs/{run_id}/differences")
async def list_differences(
    run_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    min_severity: Severity = Severity.LOW,
    limit: Annotated[int, Query(ge=1, le=1000)] = 500,
) -> list[RunDifference]:
    """Every difference of a run at or above a severity, most severe first.

    The default leaves out severity "none", which is the noise.
    """
    run = await get_child(session, Run, principal.workspace_id, run_id)
    wanted = [severity.value for severity in Severity if severity.rank >= min_severity.rank]
    # Ordering and the limit are done by the database, so a run with many
    # differences costs no more than the rows asked for.
    rank = case({severity.value: severity.rank for severity in Severity}, value=Difference.severity)
    rows = await session.execute(
        select(Difference, StepResult.step_id, CaseResult.id, CaseResult.name)
        .join(StepResult, Difference.step_result_id == StepResult.id)
        .join(CaseResult, StepResult.case_result_id == CaseResult.id)
        .where(Difference.run_id == run.id, Difference.severity.in_(wanted))
        .order_by(rank.desc(), CaseResult.position, StepResult.position, Difference.position)
        .limit(limit)
    )
    return [
        RunDifference(
            **_difference_fields(difference),
            case_result_id=case_id,
            case_name=case_name,
            step_id=step_id,
        )
        for difference, step_id, case_id, case_name in rows
    ]


def _difference_fields(difference: Difference) -> dict[str, Any]:
    return {
        "id": difference.id,
        "kind": difference.kind,
        "path": difference.path,
        "old_value": difference.old_value,
        "new_value": difference.new_value,
        "detail": difference.detail,
        "severity": difference.severity,
        "reason": difference.reason,
        "noise_source": difference.noise_source,
        "hints": difference.hints,
    }


@router.get("/case-results/{case_result_id}")
async def read_case_result(
    case_result_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> CaseResultDetail:
    """One case in full: both requests and responses for every step, and what differed."""
    owned = await get_case_result(session, principal.workspace_id, case_result_id)
    # selectinload: fetch the steps, then all their differences, in two
    # further queries. With async sessions related rows must be loaded
    # explicitly; touching an unloaded relationship is an error, not a
    # hidden query.
    case = await session.scalar(
        select(CaseResult)
        .where(CaseResult.id == owned.id)
        .options(selectinload(CaseResult.steps).selectinload(StepResult.differences))
    )
    return CaseResultDetail.model_validate(case)
