"""The worker: takes queued runs, executes them, stores the results.

The `runs` table is the queue. A worker claims a run with

    SELECT ... WHERE status = 'queued' FOR UPDATE SKIP LOCKED

which locks the row it takes and skips rows another worker has locked, so
several workers can poll the same table without ever taking the same run.

While a run executes, no database connection is held. HTTP requests to
the APIs under test can take a long time, and a connection pool is small.
"""

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import httpx2
from paritylens_engine.executor import Executor
from paritylens_engine.redact import Redactor
from paritylens_engine.report import RunReport
from paritylens_engine.suite import Suite
from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from paritylens_api.ai.analyzer import collect_findings, request_analysis, store_analyses
from paritylens_api.ai.factory import initial_ai_status, provider_for
from paritylens_api.ai.provider import LLMError, LLMProvider
from paritylens_api.core.config import Settings
from paritylens_api.core.crypto import DecryptionError, Encrypted, SecretBox, secret_context
from paritylens_api.models import Project, Run, Secret, Session, TestCase
from paritylens_api.services.egress import egress_policy
from paritylens_api.services.reports import save_report
from paritylens_api.services.suites import referenced_secrets, resolve_suite, snapshot_case_ids

logger = logging.getLogger("paritylens.worker")

# A run may execute for this long before it is abandoned.
RUN_DEADLINE = timedelta(minutes=10)
# A run still "running" after this long lost its worker. Longer than the
# deadline, so a live run is never mistaken for a dead one.
STALE_AFTER = timedelta(minutes=15)
# An analysis is one call to a model; the provider's own timeout is shorter.
ANALYSIS_DEADLINE = timedelta(minutes=5)
ANALYSIS_STALE_AFTER = timedelta(minutes=10)
IDLE_SLEEP_SECONDS = 1.0
SWEEP_EVERY_SECONDS = 60.0

type SessionFactory = async_sessionmaker[AsyncSession]
type Step = Callable[[SessionFactory, Settings], Awaitable[bool]]


class RunCannotStartError(Exception):
    """The run cannot be executed. The message is stored on the run and shown to the user."""


async def claim_next_run(sessions: SessionFactory) -> uuid.UUID | None:
    """Take the oldest queued run and mark it running. None if the queue is empty."""
    async with sessions() as session, session.begin():
        run = await session.scalar(
            select(Run)
            .where(Run.status == "queued")
            .order_by(Run.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if run is None:
            return None
        run.status = "running"
        run.started_at = datetime.now(UTC)
        return run.id


async def fail_stale_runs(sessions: SessionFactory) -> int:
    """Mark runs whose worker died as failed, so they do not stay "running" forever."""
    cutoff = datetime.now(UTC) - STALE_AFTER
    async with sessions() as session, session.begin():
        result = await session.execute(
            update(Run)
            .where(Run.status == "running", Run.started_at < cutoff)
            .values(
                status="failed",
                finished_at=datetime.now(UTC),
                error="the worker stopped before the run finished",
            )
            .returning(Run.id)
        )
        return len(result.all())


async def purge_old_runs(sessions: SessionFactory, *, days: int) -> int:
    """Delete runs older than the retention period, results included.

    Stored responses can contain personal data from the systems under
    test. They are kept as long as they are useful, not forever.
    """
    cutoff = datetime.now(UTC) - timedelta(days=days)
    async with sessions() as session, session.begin():
        result = await session.execute(delete(Run).where(Run.created_at < cutoff).returning(Run.id))
        return len(result.all())


async def purge_expired_sessions(sessions: SessionFactory) -> int:
    async with sessions() as session, session.begin():
        result = await session.execute(
            delete(Session).where(Session.expires_at < datetime.now(UTC)).returning(Session.id)
        )
        return len(result.all())


async def _load(
    sessions: SessionFactory, run_id: uuid.UUID, box: SecretBox
) -> tuple[Suite, Redactor, list[uuid.UUID]]:
    """Read what the run needs and close the session again."""
    async with sessions() as session:
        run = await session.get(Run, run_id)
        if run is None or run.suite_snapshot is None:
            raise RunCannotStartError("the run has nothing to execute")

        secrets: dict[str, str] = {}
        needed = referenced_secrets(run.suite_snapshot)
        if needed:
            rows = await session.scalars(
                select(Secret).where(Secret.project_id == run.project_id, Secret.name.in_(needed))
            )
            for row in rows:
                try:
                    secrets[row.name] = box.decrypt(
                        Encrypted(row.ciphertext, row.nonce, row.key_version),
                        context=secret_context(run.project_id, row.name),
                    )
                except DecryptionError as exc:
                    raise RunCannotStartError(f"secret {row.name} could not be decrypted") from exc
        missing = needed - secrets.keys()
        if missing:
            raise RunCannotStartError(f"secrets no longer set: {', '.join(sorted(missing))}")

        suite = resolve_suite(run.suite_snapshot, secrets)
        case_ids = snapshot_case_ids(run.suite_snapshot)
    return suite, Redactor(secrets.values()), case_ids


async def _save(
    sessions: SessionFactory,
    run_id: uuid.UUID,
    report: RunReport,
    case_ids: list[uuid.UUID],
    settings: Settings,
) -> bool:
    """Store the report. False if the run is gone or no longer waiting for one."""
    async with sessions() as session, session.begin():
        run = await session.scalar(select(Run).where(Run.id == run_id).with_for_update())
        # Deleted while it ran, or already written off as stale: either
        # way the outcome was decided elsewhere and is not overwritten.
        if run is None or run.status != "running":
            return False
        # Test cases can be deleted while their run executes. Link each
        # result only to a test case that still exists.
        existing = set(await session.scalars(select(TestCase.id).where(TestCase.id.in_(case_ids))))
        links = [case_id if case_id in existing else None for case_id in case_ids]
        # Pad defensively: the report always has one case per snapshot case.
        links += [None] * (len(report.cases) - len(links))
        save_report(session, run, report, links)
        project = await session.get(Project, run.project_id)
        if project is not None:
            run.ai_status = initial_ai_status(project, settings)
        return True


async def execute_run(
    sessions: SessionFactory,
    run_id: uuid.UUID,
    settings: Settings,
    *,
    transport: httpx2.AsyncBaseTransport | None = None,
) -> None:
    """Execute a claimed run and store its outcome. Never raises."""
    started = time.perf_counter()
    try:
        box = SecretBox(settings.master_key, settings.master_key_version)
        suite, redactor, case_ids = await _load(sessions, run_id, box)
        executor = Executor(policy=egress_policy(settings), redactor=redactor, transport=transport)
        try:
            # One slow target must not hold the queue for hours.
            async with asyncio.timeout(RUN_DEADLINE.total_seconds()):
                report = await executor.run(suite)
        except TimeoutError as exc:
            minutes = int(RUN_DEADLINE.total_seconds() // 60)
            raise RunCannotStartError(f"the run took longer than {minutes} minutes") from exc
        saved = await _save(sessions, run_id, report, case_ids, settings)
        logger.info(
            "run completed" if saved else "run result discarded",
            extra={
                "run_id": str(run_id),
                "duration_ms": round((time.perf_counter() - started) * 1000),
                "cases": report.summary.total,
                "breaking": report.summary.breaking,
                "errors": report.summary.error,
            },
        )
    except Exception as exc:
        # Deliberately broad: whatever went wrong, the run must end up
        # "failed" with a reason, not stuck in "running".
        message = str(exc) if isinstance(exc, RunCannotStartError) else type(exc).__name__
        logger.exception("run failed", extra={"run_id": str(run_id)})
        async with sessions() as session, session.begin():
            await session.execute(
                update(Run)
                .where(Run.id == run_id, Run.status == "running")
                .values(status="failed", finished_at=datetime.now(UTC), error=message)
            )


async def claim_next_analysis(sessions: SessionFactory) -> uuid.UUID | None:
    """Take the oldest completed run that is waiting for AI analysis."""
    async with sessions() as session, session.begin():
        while True:
            run = await session.scalar(
                select(Run)
                .where(Run.ai_status == "pending", Run.status == "completed")
                .order_by(Run.created_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if run is None:
                return None
            # Asked again here, at the last moment before data leaves: the
            # project may have opted out since the analysis was queued.
            project = await session.get(Project, run.project_id)
            if project is not None and project.ai_enabled:
                break
            run.ai_status = "none"
            await session.flush()
        run.ai_status = "running"
        run.ai_error = None
        run.ai_started_at = datetime.now(UTC)
        run.ai_attempts += 1
        return run.id


async def fail_stale_analyses(sessions: SessionFactory) -> int:
    """Mark analyses that never finished as failed.

    Failed, not queued again: whatever stopped it (a worker killed for
    using too much memory, say) would likely stop it again, and each
    attempt is a paid call. A person can ask for another from the run page.

    Only by age, never "everything running at startup": another worker may
    be in the middle of one, and during a deployment old and new workers
    overlap.
    """
    cutoff = datetime.now(UTC) - ANALYSIS_STALE_AFTER
    async with sessions() as session, session.begin():
        result = await session.execute(
            update(Run)
            .where(
                Run.ai_status == "running",
                or_(Run.ai_started_at.is_(None), Run.ai_started_at < cutoff),
            )
            .values(ai_status="failed", ai_error="the analysis was interrupted")
            .returning(Run.id)
        )
        return len(result.all())


async def analyze_once(
    sessions: SessionFactory, settings: Settings, *, provider: LLMProvider | None = None
) -> bool:
    """Claim one run and have its findings analysed. False if none was waiting.

    Whatever happens here, the run itself is untouched: it is completed and
    stays completed. Only ai_status and the ai_analyses table change.
    """
    run_id = await claim_next_analysis(sessions)
    if run_id is None:
        return False
    started = time.perf_counter()
    status, error, stored = "completed", None, 0
    try:
        provider = provider or provider_for(settings)
        if provider is None:
            status = "skipped"
        else:
            async with asyncio.timeout(ANALYSIS_DEADLINE.total_seconds()):
                # Three separate steps, so that no database connection is
                # held while waiting for the model.
                async with sessions() as session:
                    findings = await collect_findings(session, run_id)
                analyses = await request_analysis(provider, findings) if findings else {}
                async with sessions() as session, session.begin():
                    await store_analyses(session, run_id, analyses, provider)
            stored = len(analyses)
    except LLMError as exc:
        status, error = "failed", str(exc)
    except TimeoutError:
        minutes = int(ANALYSIS_DEADLINE.total_seconds() // 60)
        status, error = "failed", f"the analysis took longer than {minutes} minutes"
    except Exception as exc:
        status, error = "failed", type(exc).__name__
        logger.exception("analysis failed", extra={"run_id": str(run_id)})

    # If this update cannot be made (the database is away), the analysis
    # stays "running" and fail_stale_analyses ends it later.
    async with sessions() as session, session.begin():
        await session.execute(
            update(Run)
            .where(Run.id == run_id, Run.ai_status == "running")
            .values(ai_status=status, ai_error=error)
        )
    logger.info(
        "analysis finished",
        extra={
            "run_id": str(run_id),
            "status": status,
            "analyses": stored,
            "model": provider.model if provider else None,
            "duration_ms": round((time.perf_counter() - started) * 1000),
        },
    )
    return True


async def work_once(
    sessions: SessionFactory,
    settings: Settings,
    *,
    transport: httpx2.AsyncBaseTransport | None = None,
) -> bool:
    """Claim and execute one run. Returns False if there was nothing to do."""
    run_id = await claim_next_run(sessions)
    if run_id is None:
        return False
    logger.info("run claimed", extra={"run_id": str(run_id)})
    await execute_run(sessions, run_id, settings, transport=transport)
    return True


async def sweep(sessions: SessionFactory, settings: Settings) -> None:
    """Housekeeping between runs."""
    await fail_stale_runs(sessions)
    await fail_stale_analyses(sessions)
    purged = await purge_old_runs(sessions, days=settings.result_retention_days)
    expired = await purge_expired_sessions(sessions)
    if purged or expired:
        logger.info("purged", extra={"runs": purged, "sessions": expired})


async def _run_step(sessions: SessionFactory, settings: Settings) -> bool:
    return await work_once(sessions, settings)


async def _analysis_step(sessions: SessionFactory, settings: Settings) -> bool:
    return await analyze_once(sessions, settings)


async def _sweep_step(sessions: SessionFactory, settings: Settings) -> bool:
    await sweep(sessions, settings)
    return False  # never "more to do right now": always wait before the next


async def _poll(
    name: str,
    step: Step,
    sessions: SessionFactory,
    settings: Settings,
    *,
    idle_seconds: float = IDLE_SLEEP_SECONDS,
) -> None:
    """Call `step` for ever: again at once while it finds work, after a pause when it does not."""
    failures = 0
    while True:
        try:
            worked = await step(sessions, settings)
            failures = 0
        except Exception:
            # The database being briefly unreachable must not end the
            # worker. Wait, a little longer each time, and try again.
            failures += 1
            logger.exception(
                "worker iteration failed", extra={"loop": name, "consecutive": failures}
            )
            await asyncio.sleep(min(2.0**failures, 60.0))
            continue
        if not worked:
            await asyncio.sleep(idle_seconds)


async def run_forever(sessions: SessionFactory, settings: Settings) -> None:
    """Three loops side by side, so a slow model never delays a run.

    All of them spend their time awaiting the network, which is what one
    thread with asyncio is good at; none holds a database connection
    while it waits.
    """
    logger.info("worker started", extra={"egress_mode": settings.egress_mode.value})
    await asyncio.gather(
        _poll("runs", _run_step, sessions, settings),
        _poll("analyses", _analysis_step, sessions, settings),
        _poll("sweep", _sweep_step, sessions, settings, idle_seconds=SWEEP_EVERY_SECONDS),
    )
