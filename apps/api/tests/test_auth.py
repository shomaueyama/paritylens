from datetime import UTC, datetime, timedelta

import httpx2
import pytest
from paritylens_api.core.config import AuthMode, Settings
from paritylens_api.core.security import hash_token
from paritylens_api.models import Session
from paritylens_api.testing import MakeClient, SignIn
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.anyio


async def test_the_api_says_how_to_sign_in(anonymous: httpx2.AsyncClient) -> None:
    assert (await anonymous.get("/auth/config")).json() == {"mode": "dev"}


async def test_without_a_session_the_api_answers_401(anonymous: httpx2.AsyncClient) -> None:
    for path in ("/me", "/projects", "/api-tokens"):
        response = await anonymous.get(path)

        assert response.status_code == 401
        assert response.headers["content-type"] == "application/problem+json"


async def test_signing_in_creates_the_user_and_a_workspace(alice: httpx2.AsyncClient) -> None:
    me = (await alice.get("/me")).json()

    assert me["email"] == "alice@example.com"
    assert me["workspace_name"] == "alice's workspace"


async def test_signing_in_again_is_the_same_account(sign_in: SignIn) -> None:
    first = (await (await sign_in("alice@example.com")).get("/me")).json()
    second = (await (await sign_in("Alice@Example.com")).get("/me")).json()

    assert (first["user_id"], first["workspace_id"]) == (second["user_id"], second["workspace_id"])


async def test_the_session_cookie_is_not_readable_by_scripts(
    anonymous: httpx2.AsyncClient,
) -> None:
    response = await anonymous.post("/auth/dev-login", json={"email": "alice@example.com"})

    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "path=/" in cookie


async def test_only_a_hash_of_the_session_token_is_stored(
    anonymous: httpx2.AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await anonymous.post("/auth/dev-login", json={"email": "alice@example.com"})
    token = anonymous.cookies["paritylens_session"]

    async with sessions() as session:
        stored = (await session.scalars(select(Session.token_hash))).all()

    assert token not in stored
    assert all(len(value) == 64 for value in stored)


async def test_signing_out_ends_the_session(alice: httpx2.AsyncClient) -> None:
    token = alice.cookies["paritylens_session"]

    assert (await alice.post("/auth/logout")).status_code == 204

    # Even a copy of the old cookie no longer works: the session is gone
    # on the server, not just forgotten by the browser.
    alice.cookies.set("paritylens_session", token)
    assert (await alice.get("/me")).status_code == 401


async def test_an_expired_session_is_refused(
    alice: httpx2.AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    async with sessions() as session, session.begin():
        await session.execute(
            update(Session).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )

    assert (await alice.get("/me")).status_code == 401


async def test_dev_login_does_not_exist_when_google_sign_in_is_configured(
    anonymous: httpx2.AsyncClient, settings: Settings
) -> None:
    settings.auth_mode = AuthMode.GOOGLE

    response = await anonymous.post("/auth/dev-login", json={"email": "alice@example.com"})

    assert response.status_code == 404


# --- cross-site requests ---------------------------------------------------------


@pytest.mark.parametrize(
    "origin", ["https://evil.example", "http://localhost:3001", "https://localhost:3000", "null"]
)
async def test_a_state_changing_request_from_another_origin_is_refused(
    alice: httpx2.AsyncClient, origin: str
) -> None:
    response = await alice.post(
        "/projects",
        json={"name": "x", "old_base_url": "http://a.test", "new_base_url": "http://b.test"},
        headers={"origin": origin},
    )

    assert response.status_code == 403


async def test_a_state_changing_request_without_an_origin_is_refused(
    make_client: MakeClient, alice: httpx2.AsyncClient
) -> None:
    async with make_client(headers={"origin": ""}) as client:
        client.headers.pop("origin")
        client.cookies.set("paritylens_session", alice.cookies["paritylens_session"])

        response = await client.post("/auth/logout")

    assert response.status_code == 403


async def test_reading_needs_no_origin(alice: httpx2.AsyncClient) -> None:
    response = await alice.get("/me", headers={"origin": "https://evil.example"})

    assert response.status_code == 200


# --- API tokens ------------------------------------------------------------------


async def test_an_api_token_authenticates_without_cookies_or_origin(
    alice: httpx2.AsyncClient, make_client: MakeClient
) -> None:
    created = (await alice.post("/api-tokens", json={"name": "ci"})).json()
    assert created["token"].startswith("plk_")

    async with make_client() as cli:
        cli.headers.pop("origin")
        cli.headers["authorization"] = f"Bearer {created['token']}"
        me = await cli.get("/me")
        project = await cli.post(
            "/projects",
            json={"name": "x", "old_base_url": "http://a.test", "new_base_url": "http://b.test"},
        )

    assert me.json()["email"] == "alice@example.com"
    assert project.status_code == 201


async def test_a_token_is_shown_once_and_only_hinted_at_afterwards(
    alice: httpx2.AsyncClient,
) -> None:
    created = (await alice.post("/api-tokens", json={"name": "ci"})).json()

    [listed] = (await alice.get("/api-tokens")).json()

    assert "token" not in listed
    assert listed["token_hint"] == created["token"][:8]
    assert listed["last_used_at"] is None


async def test_a_revoked_token_stops_working(
    alice: httpx2.AsyncClient, make_client: MakeClient
) -> None:
    created = (await alice.post("/api-tokens", json={"name": "ci"})).json()

    assert (await alice.delete(f"/api-tokens/{created['id']}")).status_code == 204

    async with make_client(headers={"authorization": f"Bearer {created['token']}"}) as cli:
        assert (await cli.get("/me")).status_code == 401
    assert (await alice.get("/api-tokens")).json() == []


async def test_a_made_up_token_is_refused(make_client: MakeClient) -> None:
    async with make_client(headers={"authorization": "Bearer plk_not-a-real-token"}) as cli:
        assert (await cli.get("/me")).status_code == 401


async def test_one_user_cannot_revoke_anothers_token(
    alice: httpx2.AsyncClient, bob: httpx2.AsyncClient
) -> None:
    created = (await alice.post("/api-tokens", json={"name": "ci"})).json()

    assert (await bob.delete(f"/api-tokens/{created['id']}")).status_code == 404
    assert len((await alice.get("/api-tokens")).json()) == 1


# --- found in review ----------------------------------------------------------------


@pytest.mark.parametrize("origin", ["http://[::1", "http://", "://", "\u00e9"])
async def test_a_malformed_origin_is_refused_not_crashed_on(
    alice: httpx2.AsyncClient, origin: str
) -> None:
    response = await alice.post("/auth/logout", headers=[(b"origin", origin.encode("utf-8"))])

    assert response.status_code == 403


async def test_an_api_token_cannot_manage_api_tokens(
    alice: httpx2.AsyncClient, make_client: MakeClient
) -> None:
    """A leaked token must not be able to mint its own replacement."""
    created = (await alice.post("/api-tokens", json={"name": "ci"})).json()

    async with make_client(headers={"authorization": f"Bearer {created['token']}"}) as cli:
        assert (await cli.post("/api-tokens", json={"name": "another"})).status_code == 403
        assert (await cli.get("/api-tokens")).status_code == 403
        assert (await cli.delete(f"/api-tokens/{created['id']}")).status_code == 403


async def test_a_tokens_last_use_is_recorded_at_most_once_a_minute(
    alice: httpx2.AsyncClient, make_client: MakeClient
) -> None:
    """Otherwise every read is a write, and requests sharing a token queue up."""
    created = (await alice.post("/api-tokens", json={"name": "ci"})).json()

    async with make_client(headers={"authorization": f"Bearer {created['token']}"}) as cli:
        await cli.get("/me")
        first = (await alice.get("/api-tokens")).json()[0]["last_used_at"]
        await cli.get("/me")
        second = (await alice.get("/api-tokens")).json()[0]["last_used_at"]

    assert first is not None
    assert second == first


async def test_expired_sessions_are_purged(
    alice: httpx2.AsyncClient, bob: httpx2.AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    from paritylens_api.worker.loop import purge_expired_sessions

    alices_token = hash_token(alice.cookies["paritylens_session"])
    async with sessions() as session, session.begin():
        await session.execute(
            update(Session)
            .where(Session.token_hash == alices_token)
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )

    assert await purge_expired_sessions(sessions) == 1
    assert (await bob.get("/me")).status_code == 200
