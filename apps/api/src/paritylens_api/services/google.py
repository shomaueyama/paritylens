"""Sign in with Google (OpenID Connect, authorization code flow with PKCE).

The flow, in three steps:

  1. /auth/google/login sends the browser to Google with a random `state`,
     a `nonce`, and the hash of a random `code_verifier`. The three values
     are kept in a short-lived signed cookie.
  2. Google sends the browser back to /auth/google/callback with a `code`.
     The `state` must match the cookie: that proves this browser started
     the flow.
  3. The server exchanges the code (plus the verifier) for an ID token,
     checks its signature, audience, issuer, expiry and nonce, and only
     then trusts the email address inside it.
"""

import base64
import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from urllib.parse import urlencode

import httpx2
import jwt

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 - an endpoint, not a credential
JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = ("https://accounts.google.com", "accounts.google.com")

FLOW_COOKIE = "paritylens_oauth"
FLOW_LIFETIME_SECONDS = 600


class OAuthError(Exception):
    """The sign-in could not be completed. The message is safe to show."""


@dataclass(frozen=True)
class Flow:
    """What the server must remember between redirecting out and being called back."""

    state: str
    nonce: str
    code_verifier: str

    @classmethod
    def start(cls) -> "Flow":
        return cls(
            state=secrets.token_urlsafe(32),
            nonce=secrets.token_urlsafe(32),
            code_verifier=secrets.token_urlsafe(64),
        )

    @property
    def code_challenge(self) -> str:
        digest = hashlib.sha256(self.code_verifier.encode("ascii")).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def seal_flow(flow: Flow, key: bytes, *, now: float | None = None) -> str:
    """Serialise a flow into a cookie value that cannot be forged or altered."""
    payload = json.dumps(
        {
            "state": flow.state,
            "nonce": flow.nonce,
            "code_verifier": flow.code_verifier,
            "expires": (now or time.time()) + FLOW_LIFETIME_SECONDS,
        }
    ).encode("utf-8")
    body = base64.urlsafe_b64encode(payload).decode("ascii")
    return f"{body}.{_sign(body, key)}"


def open_flow(sealed: str, key: bytes, *, now: float | None = None) -> Flow:
    body, _, signature = sealed.partition(".")
    # compare_digest: constant time, so the comparison leaks nothing
    # about how much of a forged signature was right.
    # Compared as bytes: compare_digest refuses text that is not ASCII, and
    # a cookie can contain anything.
    expected = _sign(body, key).encode("ascii")
    if not hmac.compare_digest(signature.encode("utf-8", "replace"), expected):
        raise OAuthError("the sign-in attempt could not be verified; start again")
    try:
        data = json.loads(base64.urlsafe_b64decode(body))
        expires = float(data["expires"])
        flow = Flow(state=data["state"], nonce=data["nonce"], code_verifier=data["code_verifier"])
    except (ValueError, KeyError, TypeError) as exc:
        raise OAuthError("the sign-in attempt could not be verified; start again") from exc
    if expires < (now or time.time()):
        raise OAuthError("the sign-in attempt took too long; start again")
    return flow


def _sign(body: str, key: bytes) -> str:
    # "replace": a cookie can hold any characters; signing must not fail on them.
    data = b"oauth-flow:" + body.encode("utf-8", "replace")
    return hmac.new(key, data, hashlib.sha256).hexdigest()


def authorization_url(flow: Flow, *, client_id: str, redirect_uri: str) -> str:
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": flow.state,
            "nonce": flow.nonce,
            "code_challenge": flow.code_challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


async def exchange_code(
    client: httpx2.AsyncClient,
    *,
    code: str,
    flow: Flow,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> str:
    """Trade the authorization code for an ID token."""
    try:
        response = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": flow.code_verifier,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
            },
        )
    except httpx2.HTTPError as exc:
        raise OAuthError("could not reach Google; try again") from exc
    if response.status_code != 200:
        raise OAuthError("Google rejected the sign-in; start again")
    id_token = response.json().get("id_token")
    if not isinstance(id_token, str):
        raise OAuthError("Google did not return an identity; start again")
    return id_token


@dataclass(frozen=True)
class Identity:
    sub: str
    email: str
    name: str


# Looks up the public key that signed a token. Injected so tests can sign
# tokens with their own key instead of calling Google.
type KeyResolver = Callable[[str], Any]


@lru_cache
def _jwks_client() -> jwt.PyJWKClient:
    # One client for the life of the process, so that Google's keys are
    # fetched once and cached, not on every sign-in.
    return jwt.PyJWKClient(JWKS_URL, cache_keys=True, lifespan=3600)


def google_key_resolver() -> KeyResolver:
    return lambda token: _jwks_client().get_signing_key_from_jwt(token).key


def verify_id_token(id_token: str, *, flow: Flow, client_id: str, key_for: KeyResolver) -> Identity:
    try:
        claims = jwt.decode(
            id_token,
            key_for(id_token),
            # Named explicitly. Accepting whatever algorithm the token
            # claims would let an attacker pick "none" or a symmetric one.
            algorithms=["RS256"],
            audience=client_id,
            issuer=ISSUERS,
            # Tolerate clocks that disagree by a few seconds.
            leeway=30,
            options={"require": ["exp", "iat", "sub", "aud", "iss"]},
        )
    except jwt.PyJWTError as exc:
        raise OAuthError("Google's response could not be verified; start again") from exc

    if not hmac.compare_digest(str(claims.get("nonce", "")), flow.nonce):
        raise OAuthError("the sign-in attempt could not be verified; start again")
    email = claims.get("email")
    if not isinstance(email, str) or claims.get("email_verified") is not True:
        raise OAuthError("the Google account has no verified email address")
    return Identity(sub=str(claims["sub"]), email=email, name=str(claims.get("name") or ""))
