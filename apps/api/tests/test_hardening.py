"""Inputs that used to produce a 500, a leak, or a stuck state. Found in review."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx2
import pytest
from paritylens_api.core.limits import DEFAULT_MAX_BYTES
from paritylens_api.db import get_session
from paritylens_api.models import User, Workspace, WorkspaceMember
from paritylens_api.services.auth import find_or_create_user
from paritylens_api.testing import ORIGIN, PROJECT, MakeClient, create_project
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

pytestmark = pytest.mark.anyio


def tolerant_client(
    make_client: MakeClient, cookies: httpx2.Cookies | None = None
) -> httpx2.AsyncClient:
    """A client that reports a server error as a 500 response instead of raising."""
    app = make_client.app  # type: ignore[attr-defined]
    return httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app, raise_app_exceptions=False),
        base_url=f"{ORIGIN}/api/v1",
        headers={"origin": ORIGIN},
        cookies=cookies,
    )


# --- values the database cannot store are refused, not passed on -----------------------


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/projects", PROJECT | {"name": "a\x00b"}),
        ("/projects", PROJECT | {"description": "\x00"}),
        ("/projects", PROJECT | {"old_headers": {"X-A": "a\x00"}}),
    ],
)
async def test_nul_characters_are_a_client_error(
    alice: httpx2.AsyncClient, path: str, body: dict[str, Any]
) -> None:
    response = await alice.post(path, json=body)

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("suffix", "body"),
    [
        ("/endpoints", {"method": "GET", "path_template": "/a\x00"}),
        ("/rules", {"kind": "ignore", "path": "$.a\x00"}),
        ("/test-cases", {"name": "a\x00", "steps": [{"request": {"method": "GET", "path": "/"}}]}),
        (
            "/test-cases",
            {
                "name": "a",
                "steps": [{"request": {"method": "POST", "path": "/", "json": {"k": "\x00"}}}],
            },
        ),
    ],
)
async def test_nul_characters_in_project_children_are_a_client_error(
    alice: httpx2.AsyncClient, suffix: str, body: dict[str, Any]
) -> None:
    project = await create_project(alice)

    response = await alice.post(f"/projects/{project['id']}{suffix}", json=body)

    assert response.status_code == 422


async def test_a_path_too_long_for_its_index_is_a_client_error(alice: httpx2.AsyncClient) -> None:
    project = await create_project(alice)

    response = await alice.post(
        f"/projects/{project['id']}/endpoints",
        json={"method": "GET", "path_template": "/" + "\u65e5" * 1999},
    )

    assert response.status_code == 422


async def test_a_secret_with_a_stray_newline_is_refused_when_saved(
    alice: httpx2.AsyncClient,
) -> None:
    """Not accepted now and then failing every run with an opaque error."""
    project = await create_project(alice)

    response = await alice.put(
        f"/projects/{project['id']}/secrets/TOKEN", json={"value": "tok3n\n"}
    )

    assert response.status_code == 422
    assert "tok3n" not in response.text


async def test_any_header_name_can_be_compared(alice: httpx2.AsyncClient) -> None:
    """Content-Length cannot be *sent*, but there is every reason to compare it."""
    project = await create_project(alice)
    path = f"/projects/{project['id']}/rules"

    for name in ("Content-Length", "Connection", "Transfer-Encoding"):
        response = await alice.post(path, json={"kind": "compare_header", "path": name})
        assert response.status_code == 201


# --- OpenAPI documents -------------------------------------------------------------------


async def test_an_openapi_document_with_yaml_dates_imports(alice: httpx2.AsyncClient) -> None:
    project = await create_project(alice)
    document = "info: {version: 2020-01-01}\npaths:\n  /orders:\n    get: {}\n"

    response = await alice.post(f"/projects/{project['id']}/openapi", json={"document": document})

    assert response.status_code == 200
    assert response.json()["created"] == 1


@pytest.mark.parametrize(
    "document",
    [
        # Anchors that expand tenfold per level: a few hundred bytes, billions of nodes.
        "\n".join(
            ["a0: &a0 [x,x,x,x,x,x,x,x,x,x]"]
            + [f"a{n}: &a{n} [{','.join([f'*a{n - 1}'] * 10)}]" for n in range(1, 9)]
            + ["paths: {}"]
        ),
        "x: &a [*a]\npaths: {}",  # a structure that contains itself
        "paths: {}\nx: .inf",
        "paths: {}\nx: .nan",
        '{"paths": {}, "x": 1e999}',
        "paths: {}\nx: !!binary aGVsbG8=",
        "[" * 100_000,
    ],
)
async def test_a_hostile_openapi_document_is_refused_quickly(
    alice: httpx2.AsyncClient, document: str
) -> None:
    project = await create_project(alice)

    async with asyncio.timeout(5):
        response = await alice.post(
            f"/projects/{project['id']}/openapi", json={"document": document}
        )

    assert response.status_code == 422


# --- request size --------------------------------------------------------------------------


async def test_an_oversized_body_is_refused_before_authentication(
    anonymous: httpx2.AsyncClient,
) -> None:
    """413, not 401: nothing read the body to find out who was asking."""
    response = await anonymous.post(
        "/projects",
        content=b"x" * (DEFAULT_MAX_BYTES + 1),
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 413


async def test_a_body_without_a_declared_length_is_cut_off_at_the_limit(
    alice: httpx2.AsyncClient,
) -> None:
    async def endless() -> AsyncIterator[bytes]:
        for _ in range(100):
            yield b"x" * 65536

    response = await alice.post(
        "/projects", content=endless(), headers={"content-type": "application/json"}
    )

    assert response.status_code == 413


# --- errors nobody anticipated ---------------------------------------------------------------


async def test_an_unexpected_error_is_a_plain_500_and_logs_no_message(
    alice: httpx2.AsyncClient,
    make_client: MakeClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def explode(*args: object) -> None:
        raise RuntimeError("failed with Authorization: Bearer s3cr3t-token")

    monkeypatch.setattr("paritylens_api.routers.projects.check_targets", explode)

    async with tolerant_client(make_client, alice.cookies) as client:
        with caplog.at_level(logging.INFO):
            response = await client.post("/projects", json=PROJECT)

    assert response.status_code == 500
    assert response.json() == {
        "type": "about:blank",
        "title": "Internal Server Error",
        "status": 500,
    }
    assert "s3cr3t" not in caplog.text
    assert any(getattr(record, "error_type", None) == "RuntimeError" for record in caplog.records)


async def test_a_failed_commit_is_reported_to_the_client(
    alice: httpx2.AsyncClient, make_client: MakeClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """The commit runs before the response is sent, so its failure is the response."""

    async def session_whose_commit_fails() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            yield session
            raise ConnectionError("the database went away during commit")

    app = make_client.app  # type: ignore[attr-defined]
    original = app.dependency_overrides[get_session]
    app.dependency_overrides[get_session] = session_whose_commit_fails
    try:
        async with tolerant_client(make_client, alice.cookies) as client:
            response = await client.post("/projects", json=PROJECT)
    finally:
        app.dependency_overrides[get_session] = original

    assert response.status_code == 500


# --- first sign-ins arriving together -----------------------------------------------------------


async def test_concurrent_first_sign_ins_create_one_account(database_url: str) -> None:
    """Real, separate connections: this is about what happens between transactions."""
    engine = create_async_engine(database_url, pool_size=8)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    email = "racing@example.com"

    async def sign_in() -> None:
        async with factory() as session, session.begin():
            await find_or_create_user(session, email=email)

    try:
        await asyncio.gather(*(sign_in() for _ in range(8)))

        async with factory() as session:
            users = (await session.scalars(select(User).where(User.email == email))).all()
            assert len(users) == 1
            workspaces = await session.scalar(
                select(func.count())
                .select_from(WorkspaceMember)
                .where(WorkspaceMember.user_id == users[0].id)
            )
            assert workspaces == 1
    finally:
        async with factory() as session, session.begin():
            owned = (
                select(WorkspaceMember.workspace_id)
                .join(User, User.id == WorkspaceMember.user_id)
                .where(User.email == email)
            )
            await session.execute(delete(Workspace).where(Workspace.id.in_(owned)))
            await session.execute(delete(User).where(User.email == email))
        await engine.dispose()


async def test_the_json_log_of_a_request_has_no_query_string(
    alice: httpx2.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    project = await create_project(alice)

    with caplog.at_level(logging.INFO, logger="paritylens.api"):
        await alice.get(f"/projects/{project['id']}/runs?before=s3cr3t-looking-value")

    [record] = [r for r in caplog.records if r.getMessage() == "request"]
    assert record.route == "/projects/{project_id}/runs"  # type: ignore[attr-defined]
    assert "s3cr3t" not in json.dumps(record.__dict__, default=str)
