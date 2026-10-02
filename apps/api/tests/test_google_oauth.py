"""Sign in with Google, with Google replaced by a local key pair and a fake token endpoint."""

import time
from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx2
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from paritylens_api.core.config import AuthMode, Settings
from paritylens_api.routers.auth import get_http_client, get_key_resolver
from paritylens_api.services import google
from paritylens_api.services.auth import find_or_create_user
from paritylens_api.testing import MakeClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.anyio

CLIENT_ID = "paritylens-test.apps.googleusercontent.com"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
FLOW_KEY = b"k" * 32


def id_token(*, nonce: str, key: Any = KEY, algorithm: str = "RS256", **overrides: Any) -> str:
    now = int(time.time())
    claims = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": "google-user-1",
        "email": "alice@example.com",
        "email_verified": True,
        "name": "Alice",
        "nonce": nonce,
        "iat": now,
        "exp": now + 300,
    } | overrides
    return jwt.encode(claims, key, algorithm=algorithm)


def verify(token: str, flow: google.Flow) -> google.Identity:
    return google.verify_id_token(
        token, flow=flow, client_id=CLIENT_ID, key_for=lambda _: KEY.public_key()
    )


# --- the signed cookie that carries the flow --------------------------------------


def test_a_flow_survives_the_round_trip_through_its_cookie() -> None:
    flow = google.Flow.start()

    assert google.open_flow(google.seal_flow(flow, FLOW_KEY), FLOW_KEY) == flow


def test_a_flow_cookie_that_was_altered_is_refused() -> None:
    sealed = google.seal_flow(google.Flow.start(), FLOW_KEY)
    body, signature = sealed.split(".")

    for forged in (f"{body[:-2]}AA.{signature}", f"{body}.{'0' * 64}", "garbage", ""):
        with pytest.raises(google.OAuthError):
            google.open_flow(forged, FLOW_KEY)


def test_a_flow_cookie_signed_with_another_key_is_refused() -> None:
    sealed = google.seal_flow(google.Flow.start(), b"x" * 32)

    with pytest.raises(google.OAuthError):
        google.open_flow(sealed, FLOW_KEY)


def test_a_flow_expires() -> None:
    sealed = google.seal_flow(google.Flow.start(), FLOW_KEY, now=1000.0)

    with pytest.raises(google.OAuthError, match="took too long"):
        google.open_flow(sealed, FLOW_KEY, now=1000.0 + google.FLOW_LIFETIME_SECONDS + 1)


def test_the_authorization_url_carries_state_nonce_and_pkce() -> None:
    flow = google.Flow.start()

    url = google.authorization_url(flow, client_id=CLIENT_ID, redirect_uri="https://app/cb")

    query = parse_qs(urlsplit(url).query)
    assert url.startswith("https://accounts.google.com/")
    assert query["state"] == [flow.state]
    assert query["nonce"] == [flow.nonce]
    assert query["code_challenge"] == [flow.code_challenge]
    assert query["code_challenge_method"] == ["S256"]
    # The verifier itself stays on the server; only its hash is sent.
    assert flow.code_verifier not in url


# --- verifying the ID token -------------------------------------------------------


def test_a_valid_id_token_yields_the_identity() -> None:
    flow = google.Flow.start()

    identity = verify(id_token(nonce=flow.nonce), flow)

    assert identity == google.Identity(sub="google-user-1", email="alice@example.com", name="Alice")


@pytest.mark.parametrize(
    "overrides",
    [
        {"aud": "some-other-app"},  # issued for a different application
        {"iss": "https://accounts.evil.example"},
        {"exp": int(time.time()) - 120},
        {"email_verified": False},
        {"email": None},
        {"nonce": "not-the-one-we-sent"},  # a token replayed from another sign-in
    ],
)
def test_an_id_token_with_a_wrong_claim_is_refused(overrides: dict[str, Any]) -> None:
    flow = google.Flow.start()

    with pytest.raises(google.OAuthError):
        verify(id_token(**({"nonce": flow.nonce} | overrides)), flow)


def test_an_id_token_signed_by_someone_else_is_refused() -> None:
    flow = google.Flow.start()

    with pytest.raises(google.OAuthError):
        verify(id_token(nonce=flow.nonce, key=OTHER_KEY), flow)


def test_the_token_cannot_choose_its_own_algorithm() -> None:
    """The classic attack: sign with HS256 using the public key as the secret."""
    flow = google.Flow.start()
    public_pem = KEY.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    unsigned = jwt.encode({"sub": "x", "nonce": flow.nonce}, key="", algorithm="none")

    with pytest.raises(google.OAuthError):
        google.verify_id_token(
            unsigned, flow=flow, client_id=CLIENT_ID, key_for=lambda _: public_pem
        )
    with pytest.raises(google.OAuthError):
        google.verify_id_token(
            "not.a.jwt", flow=flow, client_id=CLIENT_ID, key_for=lambda _: public_pem
        )


# --- accounts ---------------------------------------------------------------------


async def test_a_google_account_is_recognised_by_its_id_not_its_email(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with sessions() as session:
        first = await find_or_create_user(session, email="a@example.com", google_sub="sub-1")
        # The same person after changing their address.
        again = await find_or_create_user(session, email="new@example.com", google_sub="sub-1")

        assert again.id == first.id


async def test_an_address_owned_by_one_google_account_is_not_handed_to_another(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with sessions() as session:
        await find_or_create_user(session, email="a@example.com", google_sub="sub-1")

        with pytest.raises(ValueError, match="belongs to another account"):
            await find_or_create_user(session, email="a@example.com", google_sub="sub-2")


# --- the two endpoints, end to end ------------------------------------------------


@pytest.fixture
def google_mode(settings: Settings, make_client: MakeClient) -> Iterator[dict[str, Any]]:
    """Switch the app to Google sign-in, with a fake token endpoint.

    The returned dict lets a test set the ID token that endpoint will issue.
    """
    settings.auth_mode = AuthMode.GOOGLE
    settings.google_client_id = CLIENT_ID
    settings.google_client_secret = "client-secret"
    issued: dict[str, Any] = {"requests": []}

    def token_endpoint(request: httpx2.Request) -> httpx2.Response:
        issued["requests"].append(parse_qs(request.content.decode()))
        if "id_token" not in issued:
            return httpx2.Response(400, json={"error": "invalid_grant"})
        return httpx2.Response(200, json={"id_token": issued["id_token"]})

    app = make_client.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_key_resolver] = lambda: lambda _: KEY.public_key()
    app.dependency_overrides[get_http_client] = lambda: httpx2.AsyncClient(
        transport=httpx2.MockTransport(token_endpoint)
    )
    yield issued


async def start(client: httpx2.AsyncClient) -> dict[str, str]:
    """Begin a sign-in and return the parameters sent to Google."""
    response = await client.get("/auth/google/login")
    assert response.status_code == 302
    return {k: v[0] for k, v in parse_qs(urlsplit(response.headers["location"]).query).items()}


async def test_a_complete_sign_in(
    anonymous: httpx2.AsyncClient, google_mode: dict[str, Any]
) -> None:
    sent = await start(anonymous)
    assert sent["redirect_uri"] == "http://localhost:3000/api/v1/auth/google/callback"
    google_mode["id_token"] = id_token(nonce=sent["nonce"])

    response = await anonymous.get(f"/auth/google/callback?code=the-code&state={sent['state']}")

    assert response.status_code == 302
    assert response.headers["location"] == "http://localhost:3000/projects"
    me = (await anonymous.get("/me")).json()
    assert (me["email"], me["name"]) == ("alice@example.com", "Alice")
    # The code was exchanged together with the PKCE verifier and the client secret.
    [exchange] = google_mode["requests"]
    assert exchange["code"] == ["the-code"]
    assert exchange["client_secret"] == ["client-secret"]
    assert "code_verifier" in exchange


async def test_a_callback_with_the_wrong_state_signs_nobody_in(
    anonymous: httpx2.AsyncClient, google_mode: dict[str, Any]
) -> None:
    """Someone else's authorization code, pasted into this browser."""
    sent = await start(anonymous)
    google_mode["id_token"] = id_token(nonce=sent["nonce"])

    response = await anonymous.get("/auth/google/callback?code=the-code&state=attacker-state")

    assert response.headers["location"] == "http://localhost:3000/login?error=sign_in_failed"
    assert google_mode["requests"] == []  # the code was not even exchanged
    assert (await anonymous.get("/me")).status_code == 401


async def test_a_callback_without_having_started_signs_nobody_in(
    anonymous: httpx2.AsyncClient, google_mode: dict[str, Any]
) -> None:
    response = await anonymous.get("/auth/google/callback?code=the-code&state=anything")

    assert response.headers["location"].endswith("/login?error=sign_in_failed")
    assert (await anonymous.get("/me")).status_code == 401


async def test_a_token_for_another_sign_in_attempt_signs_nobody_in(
    anonymous: httpx2.AsyncClient, google_mode: dict[str, Any]
) -> None:
    sent = await start(anonymous)
    google_mode["id_token"] = id_token(nonce="from-a-different-attempt")

    response = await anonymous.get(f"/auth/google/callback?code=c&state={sent['state']}")

    assert response.headers["location"].endswith("/login?error=sign_in_failed")
    assert (await anonymous.get("/me")).status_code == 401


async def test_google_refusing_the_code_signs_nobody_in(
    anonymous: httpx2.AsyncClient, google_mode: dict[str, Any]
) -> None:
    sent = await start(anonymous)

    response = await anonymous.get(f"/auth/google/callback?code=bad&state={sent['state']}")

    assert response.headers["location"].endswith("/login?error=sign_in_failed")


async def test_the_google_routes_do_not_exist_in_dev_mode(anonymous: httpx2.AsyncClient) -> None:
    assert (await anonymous.get("/auth/google/login")).status_code == 404
    assert (await anonymous.get("/auth/google/callback?code=c&state=s")).status_code == 404


# --- found in review ----------------------------------------------------------------


def test_a_few_seconds_of_clock_skew_are_tolerated() -> None:
    flow = google.Flow.start()
    now = int(time.time())

    # Issued "in the future" by a clock ten seconds ahead of ours.
    verify(id_token(nonce=flow.nonce, iat=now + 10), flow)


@pytest.mark.parametrize("cookie", ["abc.\u00e9", "abc.\u65e5\u672c", ".", "\u00e9"])
def test_a_flow_cookie_with_any_bytes_in_it_is_refused_not_crashed_on(cookie: str) -> None:
    with pytest.raises(google.OAuthError):
        google.open_flow(cookie, FLOW_KEY)


async def test_a_very_long_name_from_the_identity_provider_is_stored_shortened(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with sessions() as session:
        user = await find_or_create_user(
            session, email="long@example.com", name="N" * 500 + "\x00", google_sub="sub-long"
        )

        assert len(user.name) == 150
