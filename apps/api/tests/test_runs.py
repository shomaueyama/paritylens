"""Runs: queued through the API, executed by the worker, read back through the API."""

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx2
import pytest
from paritylens_api.core.config import Settings
from paritylens_api.models import Run
from paritylens_api.testing import create_project, create_test_case
from paritylens_api.worker import loop
from paritylens_api.worker.loop import (
    claim_next_run,
    execute_run,
    fail_stale_runs,
    purge_old_runs,
    work_once,
)
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.anyio

type Sessions = async_sessionmaker[AsyncSession]


def shop(request: httpx2.Request) -> httpx2.Response:
    """Stands in for both APIs: the new one is off by one yen."""
    total = 332 if request.url.host == "old.test" else 333
    return httpx2.Response(200, json={"id": "ORD-1", "total": total, "status": "accepted"})


SHOP = httpx2.MockTransport(shop)


async def queue_run(client: httpx2.AsyncClient, **project: Any) -> tuple[str, str]:
    """A project with one test case and a queued run. Returns (project_id, run_id)."""
    created = await create_project(client, **project)
    await create_test_case(client, created["id"])
    response = await client.post(f"/projects/{created['id']}/runs")
    assert response.status_code == 202, response.text
    return created["id"], response.json()["id"]


async def test_a_run_is_queued_then_executed_then_readable(
    alice: httpx2.AsyncClient, sessions: Sessions, settings: Settings
) -> None:
    _, run_id = await queue_run(alice)

    queued = (await alice.get(f"/runs/{run_id}")).json()
    assert (queued["status"], queued["source"], queued["summary"]) == ("queued", "hosted", None)

    assert await work_once(sessions, settings, transport=SHOP) is True

    run = (await alice.get(f"/runs/{run_id}")).json()
    assert run["status"] == "completed"
    assert run["summary"] == {"total": 1, "compatible": 0, "warning": 0, "breaking": 1, "error": 0}
    assert run["engine_version"] == "0.1.0"
    assert run["started_at"] <= run["finished_at"]
    [case] = run["cases"]
    assert (case["name"], case["verdict"], case["max_severity"]) == (
        "List orders",
        "breaking",
        "critical",
    )


async def test_the_result_links_back_to_the_test_case_and_shows_both_sides(
    alice: httpx2.AsyncClient, sessions: Sessions, settings: Settings
) -> None:
    project_id, run_id = await queue_run(alice)
    await work_once(sessions, settings, transport=SHOP)
    [test_case] = (await alice.get(f"/projects/{project_id}/test-cases")).json()
    [summary] = (await alice.get(f"/runs/{run_id}")).json()["cases"]

    case = (await alice.get(f"/case-results/{summary['id']}")).json()

    assert case["test_case_id"] == test_case["id"]
    [step] = case["steps"]
    assert step["outcome"] == "compared"
    assert step["old"]["request"]["url"] == "http://old.test/orders"
    assert json.loads(step["old"]["response"]["body"])["total"] == 332
    assert json.loads(step["new"]["response"]["body"])["total"] == 333
    [difference] = step["differences"]
    assert (difference["path"], difference["old_value"], difference["new_value"]) == (
        "$.total",
        332,
        333,
    )
    assert (difference["severity"], difference["reason"]) == ("critical", "critical_field_name")


async def test_the_rules_in_force_are_kept_with_the_run(
    alice: httpx2.AsyncClient, sessions: Sessions, settings: Settings
) -> None:
    project = await create_project(alice)
    await create_test_case(alice, project["id"])
    await alice.post(f"/projects/{project['id']}/rules", json={"kind": "ignore", "path": "$.total"})
    run_id = (await alice.post(f"/projects/{project['id']}/runs")).json()["id"]

    # The rule is removed after the run was requested. The run still uses it.
    [rule] = (await alice.get(f"/projects/{project['id']}/rules")).json()
    await alice.delete(f"/rules/{rule['id']}")
    await work_once(sessions, settings, transport=SHOP)

    run = (await alice.get(f"/runs/{run_id}")).json()
    assert run["rules"]["ignore"] == ["$.total"]
    assert run["summary"]["compatible"] == 1


async def test_deleting_a_test_case_keeps_its_results(
    alice: httpx2.AsyncClient, sessions: Sessions, settings: Settings
) -> None:
    project_id, run_id = await queue_run(alice)
    await work_once(sessions, settings, transport=SHOP)
    [test_case] = (await alice.get(f"/projects/{project_id}/test-cases")).json()

    await alice.delete(f"/test-cases/{test_case['id']}")

    [case] = (await alice.get(f"/runs/{run_id}")).json()["cases"]
    assert (case["name"], case["test_case_id"]) == ("List orders", None)


async def test_only_enabled_test_cases_are_run(
    alice: httpx2.AsyncClient, sessions: Sessions, settings: Settings
) -> None:
    project = await create_project(alice)
    await create_test_case(alice, project["id"], name="on")
    await create_test_case(alice, project["id"], name="off", enabled=False)
    run_id = (await alice.post(f"/projects/{project['id']}/runs")).json()["id"]

    await work_once(sessions, settings, transport=SHOP)

    assert [c["name"] for c in (await alice.get(f"/runs/{run_id}")).json()["cases"]] == ["on"]


# --- refusing to start -----------------------------------------------------------


async def test_a_project_without_enabled_test_cases_cannot_be_run(
    alice: httpx2.AsyncClient,
) -> None:
    project = await create_project(alice)
    await create_test_case(alice, project["id"], enabled=False)

    response = await alice.post(f"/projects/{project['id']}/runs")

    assert response.status_code == 422
    assert "no enabled test cases" in response.json()["detail"]


async def test_a_run_is_refused_while_a_secret_it_needs_is_not_set(
    alice: httpx2.AsyncClient,
) -> None:
    project = await create_project(
        alice, old_headers={"Authorization": "Bearer {{secret.SHOP_TOKEN}}"}
    )
    await create_test_case(alice, project["id"])

    response = await alice.post(f"/projects/{project['id']}/runs")

    assert response.status_code == 422
    assert response.json()["detail"] == "secrets not set: SHOP_TOKEN"


async def test_a_workspace_can_only_queue_so_many_runs(
    alice: httpx2.AsyncClient, bob: httpx2.AsyncClient, settings: Settings
) -> None:
    settings.max_queued_runs_per_workspace = 2
    project_id, _ = await queue_run(alice)
    assert (await alice.post(f"/projects/{project_id}/runs")).status_code == 202

    third = await alice.post(f"/projects/{project_id}/runs")

    assert third.status_code == 429
    # The limit is per workspace: Bob is unaffected.
    await queue_run(bob)


# --- secrets, end to end ---------------------------------------------------------


async def test_a_stored_secret_is_sent_to_the_api_and_appears_nowhere_else(
    alice: httpx2.AsyncClient,
    sessions: Sessions,
    settings: Settings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "s3cr3t-token-value"
    seen: list[str | None] = []

    def echoing(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.headers.get("authorization"))
        # A badly behaved API that repeats the credential in its response.
        return httpx2.Response(200, json={"you_sent": request.headers.get("authorization")})

    project = await create_project(
        alice, old_headers={"Authorization": "Bearer {{secret.SHOP_TOKEN}}"}
    )
    await create_test_case(alice, project["id"])
    await alice.put(f"/projects/{project['id']}/secrets/SHOP_TOKEN", json={"value": secret})
    run_id = (await alice.post(f"/projects/{project['id']}/runs")).json()["id"]

    with caplog.at_level(logging.DEBUG):
        await work_once(sessions, settings, transport=httpx2.MockTransport(echoing))

    # It really was sent to the old API (twice: once more for noise detection).
    assert seen.count(f"Bearer {secret}") == 2

    run = (await alice.get(f"/runs/{run_id}")).json()
    differences = (await alice.get(f"/runs/{run_id}/differences")).json()
    case = (await alice.get(f"/case-results/{run['cases'][0]['id']}")).json()
    project_now = (await alice.get(f"/projects/{project['id']}")).json()
    everything_readable = json.dumps([run, differences, case, project_now])
    assert secret not in everything_readable
    assert "[redacted]" in everything_readable

    async with sessions() as session:
        stored = (await session.scalars(select(Run))).one()
    assert secret not in json.dumps(stored.suite_snapshot)

    assert secret not in caplog.text


async def test_a_run_fails_cleanly_when_its_secret_was_deleted_meanwhile(
    alice: httpx2.AsyncClient, sessions: Sessions, settings: Settings
) -> None:
    project = await create_project(alice, new_headers={"X-Api-Key": "{{secret.NEW_KEY}}"})
    await create_test_case(alice, project["id"])
    await alice.put(f"/projects/{project['id']}/secrets/NEW_KEY", json={"value": "abc"})
    run_id = (await alice.post(f"/projects/{project['id']}/runs")).json()["id"]
    await alice.delete(f"/projects/{project['id']}/secrets/NEW_KEY")

    await work_once(sessions, settings, transport=SHOP)

    run = (await alice.get(f"/runs/{run_id}")).json()
    assert (run["status"], run["error"]) == ("failed", "secrets no longer set: NEW_KEY")


# --- the worker ------------------------------------------------------------------


async def test_an_empty_queue_means_nothing_to_do(sessions: Sessions, settings: Settings) -> None:
    assert await work_once(sessions, settings, transport=SHOP) is False


async def test_runs_are_taken_oldest_first_and_only_once(
    alice: httpx2.AsyncClient, sessions: Sessions, settings: Settings
) -> None:
    project_id, first = await queue_run(alice)
    second = (await alice.post(f"/projects/{project_id}/runs")).json()["id"]

    await work_once(sessions, settings, transport=SHOP)
    statuses = {
        run_id: (await alice.get(f"/runs/{run_id}")).json()["status"] for run_id in (first, second)
    }
    assert statuses == {first: "completed", second: "queued"}

    assert await work_once(sessions, settings, transport=SHOP) is True
    assert await work_once(sessions, settings, transport=SHOP) is False


async def test_an_unreachable_api_completes_the_run_with_error_cases(
    alice: httpx2.AsyncClient, sessions: Sessions, settings: Settings
) -> None:
    def down(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused")

    _, run_id = await queue_run(alice)

    await work_once(sessions, settings, transport=httpx2.MockTransport(down))

    run = (await alice.get(f"/runs/{run_id}")).json()
    assert run["status"] == "completed"
    assert run["summary"]["error"] == 1
    assert run["cases"][0]["verdict"] == "error"


async def test_the_worker_obeys_the_deployments_egress_policy(
    alice: httpx2.AsyncClient, sessions: Sessions, settings: Settings
) -> None:
    _, run_id = await queue_run(alice)
    # The policy tightens after the project was created.
    settings.egress_mode = settings.egress_mode.ALLOWLIST
    settings.egress_allow_hosts = "old.test"

    await work_once(sessions, settings, transport=SHOP)

    run = (await alice.get(f"/runs/{run_id}")).json()
    case = (await alice.get(f"/case-results/{run['cases'][0]['id']}")).json()
    assert "blocked by egress policy" in case["steps"][0]["new"]["error"]
    assert case["steps"][0]["old"]["error"] is None


async def test_a_run_whose_worker_died_is_marked_failed(
    alice: httpx2.AsyncClient, sessions: Sessions
) -> None:
    _, run_id = await queue_run(alice)
    async with sessions() as session, session.begin():
        await session.execute(
            update(Run).values(
                status="running", started_at=datetime.now(UTC) - timedelta(minutes=20)
            )
        )

    assert await fail_stale_runs(sessions) == 1

    run = (await alice.get(f"/runs/{run_id}")).json()
    assert (run["status"], run["error"]) == (
        "failed",
        "the worker stopped before the run finished",
    )


async def test_a_run_that_is_still_within_its_time_is_left_alone(
    alice: httpx2.AsyncClient, sessions: Sessions
) -> None:
    await queue_run(alice)
    async with sessions() as session, session.begin():
        await session.execute(update(Run).values(status="running", started_at=datetime.now(UTC)))

    assert await fail_stale_runs(sessions) == 0


# --- uploading a report ----------------------------------------------------------


def report(*, name: str = "List orders", severity: str = "high") -> dict[str, Any]:
    breaking = severity in ("high", "critical")
    return {
        "engine_version": "0.1.0",
        "started_at": "2026-10-02T00:00:00Z",
        "finished_at": "2026-10-02T00:00:03Z",
        "old_base_url": "http://internal-old.corp:8080",
        "new_base_url": "http://internal-new.corp:8080",
        "rules": {"ignore": ["$.id"]},
        "summary": {
            "total": 1,
            "compatible": 0 if breaking else 1,
            "warning": 0,
            "breaking": 1 if breaking else 0,
            "error": 0,
        },
        "cases": [
            {
                "name": name,
                "verdict": "breaking" if breaking else "compatible",
                "max_severity": severity,
                "steps": [
                    {
                        "id": "step-1",
                        "outcome": "compared",
                        "old": {"response": {"status": 200, "body": "{}"}},
                        "new": {"response": {"status": 200, "body": "{}"}},
                        "comparison": {
                            "differences": [
                                {
                                    "kind": "value_changed",
                                    "path": "$.id",
                                    "old": "a",
                                    "new": "b",
                                    "severity": "none",
                                    "reason": "ignore_rule",
                                    "noise_source": "rule",
                                },
                                {
                                    "kind": "field_added",
                                    "path": "$.currency",
                                    "new": "JPY",
                                    "severity": "low",
                                    "reason": "default_for_kind",
                                },
                                {
                                    "kind": "type_changed",
                                    "path": "$.quantity",
                                    "old": "3",
                                    "new": 3,
                                    "severity": severity,
                                    "reason": "default_for_kind",
                                },
                            ],
                            "notes": ["baseline_unavailable"],
                        },
                    }
                ],
            }
        ],
    }


async def test_a_report_from_the_cli_is_stored_like_any_other_run(
    alice: httpx2.AsyncClient,
) -> None:
    project = await create_project(alice)
    test_case = await create_test_case(alice, project["id"])

    response = await alice.post(f"/projects/{project['id']}/runs/import", json=report())

    assert response.status_code == 201
    run = (await alice.get(f"/runs/{response.json()['id']}")).json()
    assert (run["source"], run["status"]) == ("cli", "completed")
    # A CLI run can target hosts the server itself could never reach.
    assert run["old_base_url"] == "http://internal-old.corp:8080"
    assert run["rules"]["ignore"] == ["$.id"]
    # Matched to the stored test case by name.
    assert run["cases"][0]["test_case_id"] == test_case["id"]
    case = (await alice.get(f"/case-results/{run['cases'][0]['id']}")).json()
    assert case["steps"][0]["notes"] == ["baseline_unavailable"]


async def test_a_malformed_report_is_rejected(alice: httpx2.AsyncClient) -> None:
    project = await create_project(alice)
    broken = report()
    broken["cases"][0]["verdict"] = "fine"

    response = await alice.post(f"/projects/{project['id']}/runs/import", json=broken)

    assert response.status_code == 422


async def test_an_oversized_report_is_refused_before_it_is_read(
    alice: httpx2.AsyncClient,
) -> None:
    project = await create_project(alice)

    response = await alice.post(
        f"/projects/{project['id']}/runs/import",
        content=b"{}",
        headers={"content-type": "application/json", "content-length": str(64 * 1024 * 1024)},
    )

    assert response.status_code == 413


# --- reading ---------------------------------------------------------------------


async def test_differences_are_listed_most_severe_first_without_the_noise(
    alice: httpx2.AsyncClient,
) -> None:
    project = await create_project(alice)
    run_id = (await alice.post(f"/projects/{project['id']}/runs/import", json=report())).json()[
        "id"
    ]

    default = (await alice.get(f"/runs/{run_id}/differences")).json()
    high_only = (await alice.get(f"/runs/{run_id}/differences?min_severity=high")).json()
    with_noise = (await alice.get(f"/runs/{run_id}/differences?min_severity=none")).json()

    assert [(d["path"], d["severity"]) for d in default] == [
        ("$.quantity", "high"),
        ("$.currency", "low"),
    ]
    assert [d["path"] for d in high_only] == ["$.quantity"]
    assert len(with_noise) == 3
    assert (default[0]["case_name"], default[0]["step_id"]) == ("List orders", "step-1")


async def test_runs_are_paged_newest_first(alice: httpx2.AsyncClient) -> None:
    project = await create_project(alice)
    path = f"/projects/{project['id']}/runs"
    ids = [
        (await alice.post(f"{path}/import", json=report(name=f"run {n}"))).json()["id"]
        for n in range(5)
    ]

    first = (await alice.get(f"{path}?limit=2")).json()
    second = (await alice.get(f"{path}?limit=2&before={first['next_cursor']}")).json()
    third = (await alice.get(f"{path}?limit=2&before={second['next_cursor']}")).json()

    seen = [run["id"] for page in (first, second, third) for run in page["runs"]]
    assert seen == list(reversed(ids))
    assert third["next_cursor"] is None


async def test_a_bad_cursor_is_a_client_error(alice: httpx2.AsyncClient) -> None:
    project = await create_project(alice)

    response = await alice.get(f"/projects/{project['id']}/runs?before=nonsense")

    assert response.status_code == 422


async def test_an_unknown_run_is_not_found(alice: httpx2.AsyncClient) -> None:
    assert (await alice.get(f"/runs/{uuid.uuid4()}")).status_code == 404
    assert (await alice.get("/runs/not-a-uuid")).status_code == 422


async def test_runs_past_the_retention_period_are_deleted_with_their_results(
    alice: httpx2.AsyncClient, sessions: Sessions
) -> None:
    project = await create_project(alice)
    path = f"/projects/{project['id']}/runs"
    old = (await alice.post(f"{path}/import", json=report(name="old"))).json()["id"]
    recent = (await alice.post(f"{path}/import", json=report(name="recent"))).json()["id"]
    async with sessions() as session, session.begin():
        await session.execute(
            update(Run)
            .where(Run.id == uuid.UUID(old))
            .values(created_at=datetime.now(UTC) - timedelta(days=31))
        )

    assert await purge_old_runs(sessions, days=30) == 1

    assert (await alice.get(f"/runs/{old}")).status_code == 404
    assert (await alice.get(f"/runs/{recent}")).status_code == 200


# --- found in review: the worker --------------------------------------------------


async def test_a_test_case_deleted_while_its_run_executes_does_not_lose_the_results(
    alice: httpx2.AsyncClient, sessions: Sessions, settings: Settings
) -> None:
    project_id, run_id = await queue_run(alice)
    [test_case] = (await alice.get(f"/projects/{project_id}/test-cases")).json()
    claimed = await claim_next_run(sessions)
    assert claimed is not None and str(claimed) == run_id

    # Deleted after the run was claimed, before its results are saved.
    await alice.delete(f"/test-cases/{test_case['id']}")
    await execute_run(sessions, claimed, settings, transport=SHOP)

    run = (await alice.get(f"/runs/{run_id}")).json()
    assert run["status"] == "completed"
    assert (run["cases"][0]["name"], run["cases"][0]["test_case_id"]) == ("List orders", None)


async def test_results_link_to_their_own_test_case_even_when_names_repeat(
    alice: httpx2.AsyncClient, sessions: Sessions, settings: Settings
) -> None:
    project = await create_project(alice)
    first = await create_test_case(alice, project["id"], name="same name")
    second = await create_test_case(alice, project["id"], name="same name")
    run_id = (await alice.post(f"/projects/{project['id']}/runs")).json()["id"]

    await work_once(sessions, settings, transport=SHOP)

    cases = (await alice.get(f"/runs/{run_id}")).json()["cases"]
    assert [case["test_case_id"] for case in cases] == [first["id"], second["id"]]


async def test_a_run_already_written_off_is_not_revived_by_a_late_result(
    alice: httpx2.AsyncClient, sessions: Sessions, settings: Settings
) -> None:
    _, run_id = await queue_run(alice)
    claimed = await claim_next_run(sessions)
    assert claimed is not None
    async with sessions() as session, session.begin():
        await session.execute(update(Run).values(status="failed", error="written off"))

    await execute_run(sessions, claimed, settings, transport=SHOP)

    run = (await alice.get(f"/runs/{run_id}")).json()
    assert (run["status"], run["error"], run["cases"]) == ("failed", "written off", [])


async def test_a_run_that_exceeds_its_deadline_fails_with_a_reason(
    alice: httpx2.AsyncClient,
    sessions: Sessions,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def slow(request: httpx2.Request) -> httpx2.Response:
        await asyncio.sleep(5)
        return httpx2.Response(200, json={})

    monkeypatch.setattr(loop, "RUN_DEADLINE", timedelta(seconds=0.05))
    _, run_id = await queue_run(alice)

    await work_once(sessions, settings, transport=httpx2.MockTransport(slow))

    run = (await alice.get(f"/runs/{run_id}")).json()
    assert run["status"] == "failed"
    assert run["error"] == "the run took longer than 0 minutes"


async def test_the_worker_survives_the_database_being_unreachable(
    sessions: Sessions, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts: list[float] = []

    async def unreachable(*args: object, **kwargs: object) -> bool:
        raise ConnectionRefusedError("database is restarting")

    async def record_sleep(seconds: float) -> None:
        attempts.append(seconds)
        if len(attempts) == 3:
            raise asyncio.CancelledError  # stop the endless loop for the test

    monkeypatch.setattr("paritylens_api.worker.loop.asyncio.sleep", record_sleep)

    with pytest.raises(asyncio.CancelledError):
        await loop._poll("runs", unreachable, sessions, settings)

    # It kept trying, waiting longer each time.
    assert attempts == [2.0, 4.0, 8.0]


async def test_a_slow_analysis_does_not_hold_up_runs(
    sessions: Sessions, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Found in review: analyses ran inside the run loop, so one slow model
    call left queued runs, and housekeeping, waiting behind it."""
    runs_taken = 0
    enough = asyncio.Event()

    async def model_that_never_answers(*args: object, **kwargs: object) -> bool:
        await asyncio.Event().wait()
        return True

    async def take_a_run(*args: object, **kwargs: object) -> bool:
        nonlocal runs_taken
        await asyncio.sleep(0)  # as the real one does when it reads the queue
        runs_taken += 1
        if runs_taken == 3:
            enough.set()
        return True

    async def nothing(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr(loop, "analyze_once", model_that_never_answers)
    monkeypatch.setattr(loop, "work_once", take_a_run)
    monkeypatch.setattr(loop, "sweep", nothing)

    worker = asyncio.create_task(loop.run_forever(sessions, settings))
    try:
        async with asyncio.timeout(5):
            await enough.wait()
    finally:
        worker.cancel()

    assert runs_taken >= 3


# --- found in review: uploaded reports are input ------------------------------------


async def import_report(alice: httpx2.AsyncClient, body: dict[str, Any]) -> httpx2.Response:
    project = await create_project(alice)
    return await alice.post(
        f"/projects/{project['id']}/runs/import",
        content=json.dumps(body),  # json.dumps, so NaN can be sent as the literal it is
        headers={"content-type": "application/json"},
    )


async def test_the_summary_is_computed_from_the_cases_not_taken_on_trust(
    alice: httpx2.AsyncClient,
) -> None:
    lying = report() | {
        "summary": {"total": 1000000, "compatible": 999999, "warning": 0, "breaking": 0, "error": 0}
    }

    response = await import_report(alice, lying)

    assert response.status_code == 201
    assert response.json()["summary"] == {
        "total": 1,
        "compatible": 0,
        "warning": 0,
        "breaking": 1,
        "error": 0,
    }


async def test_a_case_cannot_claim_to_pass_while_holding_a_breaking_difference(
    alice: httpx2.AsyncClient,
) -> None:
    inconsistent = report()
    inconsistent["cases"][0]["verdict"] = "compatible"

    response = await import_report(alice, inconsistent)

    assert response.status_code == 422
    assert "marked compatible but holds a difference of severity high" in response.json()["detail"]


def _with(path: list[Any], value: Any) -> dict[str, Any]:
    document = report()
    target: Any = document
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return document


DIFFERENCE = ["cases", 0, "steps", 0, "comparison", "differences", 2]


@pytest.mark.parametrize(
    "bad",
    [
        _with(["engine_version"], "v" * 21),
        _with(["started_at"], "0001-01-01T00:00:00+14:00"),
        _with(["finished_at"], "9999-12-31T23:59:59-12:00"),
        _with(["finished_at"], "2026-10-01T00:00:00Z"),  # before it started
        _with(["engine_version"], "0.1\x00"),
        _with(["cases", 0, "name"], "a\x00b"),
        _with(["cases", 0, "name"], "n" * 201),
        _with(["cases", 0, "steps", 0, "id"], "s" * 201),
        _with([*DIFFERENCE, "path"], "$.a\x00"),
        _with([*DIFFERENCE, "new"], {"nested": ["\x00"]}),
        _with([*DIFFERENCE, "new"], float("nan")),
        _with([*DIFFERENCE, "new"], float("inf")),
        _with(["cases", 0, "steps", 0, "old", "response", "body"], "a\x00"),
        _with(["cases"], [report()["cases"][0]] * 501),
        _with(["cases", 0, "steps"], [report()["cases"][0]["steps"][0]] * 21),
    ],
)
async def test_a_report_the_database_cannot_hold_is_a_client_error(
    alice: httpx2.AsyncClient, bad: dict[str, Any]
) -> None:
    response = await import_report(alice, bad)

    assert response.status_code == 422


async def test_an_imported_result_is_not_linked_when_the_name_is_ambiguous(
    alice: httpx2.AsyncClient,
) -> None:
    project = await create_project(alice)
    await create_test_case(alice, project["id"])
    await create_test_case(alice, project["id"])  # the same name twice

    run = (await alice.post(f"/projects/{project['id']}/runs/import", json=report())).json()

    [case] = (await alice.get(f"/runs/{run['id']}")).json()["cases"]
    assert case["test_case_id"] is None


async def test_the_difference_limit_is_applied_after_ordering_by_severity(
    alice: httpx2.AsyncClient,
) -> None:
    project = await create_project(alice)
    run = (await alice.post(f"/projects/{project['id']}/runs/import", json=report())).json()

    [top] = (await alice.get(f"/runs/{run['id']}/differences?limit=1&min_severity=none")).json()

    assert top["severity"] == "high"


# --- findings: the run's differences, grouped by the database ----------------------


async def test_the_same_difference_in_many_cases_is_one_finding(
    alice: httpx2.AsyncClient, sessions: Sessions, settings: Settings
) -> None:
    project = await create_project(alice)
    for number in range(3):
        await create_test_case(alice, project["id"], name=f"case {number}")
    run_id = (await alice.post(f"/projects/{project['id']}/runs")).json()["id"]
    await work_once(sessions, settings, transport=SHOP)

    body = (await alice.get(f"/runs/{run_id}/findings")).json()

    assert body["truncated"] is False
    [finding] = body["findings"]
    assert (finding["signature"], finding["severity"], finding["count"]) == (
        "value_changed:$.total",
        "critical",
        3,
    )
    assert (finding["path"], finding["is_body_path"]) == ("$.total", True)
    assert [case["name"] for case in finding["cases"]] == ["case 0", "case 1", "case 2"]
    assert finding["case_count"] == 3
    assert (finding["example"]["old_text"], finding["example"]["new_text"]) == ("332", "333")


async def test_findings_include_noise_and_are_ordered_by_severity(
    alice: httpx2.AsyncClient,
) -> None:
    project = await create_project(alice)
    run = (await alice.post(f"/projects/{project['id']}/runs/import", json=report())).json()

    findings = (await alice.get(f"/runs/{run['id']}/findings")).json()["findings"]

    assert [(f["severity"], f["path"]) for f in findings] == [
        ("high", "$.quantity"),
        ("low", "$.currency"),
        ("none", "$.id"),
    ]
    assert findings[2]["example"]["noise_source"] == "rule"


async def test_a_run_with_very_many_differences_still_reports_every_finding(
    alice: httpx2.AsyncClient,
) -> None:
    """Grouping happens in the database, so nothing is cut off by a row limit."""
    big = report()
    step = big["cases"][0]["steps"][0]
    step["comparison"]["differences"] = [
        {
            "kind": "value_changed",
            "path": f"$.rows[{n}].v",
            "old": n,
            "new": n + 1,
            "severity": "medium",
            "reason": "default_for_kind",
        }
        for n in range(999)
    ] + [
        {
            "kind": "field_added",
            "path": "$.extra",
            "new": 1,
            "severity": "low",
            "reason": "default_for_kind",
        }
    ]
    big["cases"][0]["verdict"] = "warning"
    big["cases"][0]["max_severity"] = "medium"
    project = await create_project(alice)
    run = (await alice.post(f"/projects/{project['id']}/runs/import", json=big)).json()

    findings = (await alice.get(f"/runs/{run['id']}/findings")).json()["findings"]

    assert [(f["path"], f["count"]) for f in findings] == [("$.rows[*].v", 999), ("$.extra", 1)]


async def test_difference_values_are_also_given_as_exact_text(
    alice: httpx2.AsyncClient,
) -> None:
    """A browser would round the first and turn the second into 1."""
    exact = report()
    difference = exact["cases"][0]["steps"][0]["comparison"]["differences"][2]
    difference["old"], difference["new"] = 9007199254740993, 1.0
    project = await create_project(alice)
    response = await alice.post(
        f"/projects/{project['id']}/runs/import",
        content=json.dumps(exact),
        headers={"content-type": "application/json"},
    )

    [finding, *_] = (await alice.get(f"/runs/{response.json()['id']}/findings")).json()["findings"]

    assert finding["example"]["old_text"] == "9007199254740993"
    assert finding["example"]["new_text"] == "1.0"


# --- found in review: nothing failed when these were removed -------------------------


async def run_with_cases(
    alice: httpx2.AsyncClient, sessions: Sessions, settings: Settings, count: int
) -> str:
    """A run of `count` cases, each seeing a different new total. Returns the run ID."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        number = int(request.url.path.rsplit("/", 1)[1])
        old = request.url.host == "old.test"
        return httpx2.Response(200, json={"total": 100 if old else 200 + number})

    project = await create_project(alice)
    for number in range(count):
        step = {"request": {"method": "GET", "path": f"/orders/{number}"}}
        await create_test_case(alice, project["id"], name=f"case {number}", steps=[step])
    run_id: str = (await alice.post(f"/projects/{project['id']}/runs")).json()["id"]
    await work_once(sessions, settings, transport=httpx2.MockTransport(handler))
    return run_id


async def test_a_findings_example_is_its_first_occurrence_in_run_order(
    alice: httpx2.AsyncClient, sessions: Sessions, settings: Settings
) -> None:
    run_id = await run_with_cases(alice, sessions, settings, 4)

    [finding] = (await alice.get(f"/runs/{run_id}/findings")).json()["findings"]

    assert finding["example"]["new_text"] == "200"  # case 0, not whichever row came back first
    assert finding["count"] == 4


async def test_a_finding_lists_its_first_cases_and_counts_them_all(
    alice: httpx2.AsyncClient,
    sessions: Sessions,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("paritylens_api.routers.runs.MAX_CASES_PER_FINDING", 2)
    run_id = await run_with_cases(alice, sessions, settings, 4)

    [finding] = (await alice.get(f"/runs/{run_id}/findings")).json()["findings"]

    assert [case["name"] for case in finding["cases"]] == ["case 0", "case 1"]
    assert finding["case_count"] == 4


async def test_more_findings_than_can_be_listed_keeps_the_most_severe_and_says_so(
    alice: httpx2.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("paritylens_api.routers.runs.MAX_FINDINGS", 2)
    project = await create_project(alice)
    run = (await alice.post(f"/projects/{project['id']}/runs/import", json=report())).json()

    body = (await alice.get(f"/runs/{run['id']}/findings")).json()

    assert body["truncated"] is True
    assert [f["severity"] for f in body["findings"]] == ["high", "low"]
