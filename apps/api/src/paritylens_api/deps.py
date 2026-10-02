"""Dependencies that request handlers declare in their signatures.

FastAPI's `Depends` plays the role of constructor injection in ASP.NET:
a handler names what it needs, and the framework builds it per request.
There is no container to register things in; a dependency is just a
function, and its own parameters are resolved the same way.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from paritylens_api.core.config import Settings, get_settings
from paritylens_api.core.crypto import SecretBox
from paritylens_api.core.errors import ForbiddenError, UnauthorizedError
from paritylens_api.core.security import API_TOKEN_PREFIX, hash_token
from paritylens_api.db import get_session
from paritylens_api.models import ApiToken, Session, WorkspaceMember

SESSION_COOKIE = "paritylens_session"
_LAST_USED_RESOLUTION = timedelta(minutes=1)
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass(frozen=True)
class Principal:
    """Who is making the request, and which workspace they act in."""

    user_id: uuid.UUID
    workspace_id: uuid.UUID
    via: Literal["session", "api_token"]


# scope="function": the session is committed when the handler returns,
# before the response goes out. See db.get_session.
SessionDep = Annotated[AsyncSession, Depends(get_session, scope="function")]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_secret_box(settings: SettingsDep) -> SecretBox:
    return SecretBox(settings.master_key, settings.master_key_version)


SecretBoxDep = Annotated[SecretBox, Depends(get_secret_box)]


def check_origin(request: Request, settings: Settings) -> None:
    """Refuse a state-changing request that another website made the browser send.

    The session cookie is SameSite=Lax, which already keeps it off
    cross-site POSTs. This is the second lock: browsers attach an Origin
    header to such requests, and it must be this application's own.
    """
    if request.method in _SAFE_METHODS:
        return
    origin = request.headers.get("origin")
    expected = urlsplit(settings.public_base_url)
    if origin is None:
        raise ForbiddenError("the Origin header is required")
    try:
        actual = urlsplit(origin)
    except ValueError:
        actual = None  # not a URL at all
    if actual is None or (actual.scheme, actual.netloc) != (expected.scheme, expected.netloc):
        raise ForbiddenError("this request did not come from the application")


async def get_principal(request: Request, session: SessionDep, settings: SettingsDep) -> Principal:
    authorization = request.headers.get("authorization", "")
    scheme, _, credential = authorization.partition(" ")
    if scheme.lower() == "bearer" and credential.startswith(API_TOKEN_PREFIX):
        return await _from_api_token(session, credential)

    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        principal = await _from_session(session, cookie)
        # Only cookies are sent by the browser on its own, so only they
        # need the cross-site check. A bearer token has to be attached
        # deliberately by the caller.
        check_origin(request, settings)
        return principal
    raise UnauthorizedError("sign in, or send an API token")


async def _from_api_token(session: AsyncSession, token: str) -> Principal:
    row = await session.scalar(
        select(ApiToken).where(
            ApiToken.token_hash == hash_token(token), ApiToken.revoked_at.is_(None)
        )
    )
    if row is None:
        raise UnauthorizedError("the API token is not valid")
    # Recorded at most once a minute. Writing it on every request would
    # turn each read into a write and make requests that share a token
    # wait for one another's transaction.
    now = datetime.now(UTC)
    if row.last_used_at is None or now - row.last_used_at > _LAST_USED_RESOLUTION:
        row.last_used_at = now
    return Principal(user_id=row.user_id, workspace_id=row.workspace_id, via="api_token")


async def _from_session(session: AsyncSession, token: str) -> Principal:
    row = await session.scalar(
        select(Session).where(
            Session.token_hash == hash_token(token), Session.expires_at > datetime.now(UTC)
        )
    )
    if row is None:
        raise UnauthorizedError("the session has expired")
    # MVP: a user has exactly one workspace, created at first sign-in.
    workspace_id = await session.scalar(
        select(WorkspaceMember.workspace_id)
        .where(WorkspaceMember.user_id == row.user_id)
        .order_by(WorkspaceMember.created_at)
        .limit(1)
    )
    if workspace_id is None:
        raise UnauthorizedError("the account has no workspace")
    return Principal(user_id=row.user_id, workspace_id=workspace_id, via="session")


PrincipalDep = Annotated[Principal, Depends(get_principal)]


def require_browser_session(principal: PrincipalDep) -> Principal:
    """For actions an API token must not perform, such as managing API tokens.

    Otherwise a leaked token could mint its own replacement and survive
    being revoked.
    """
    if principal.via != "session":
        raise ForbiddenError("this action requires signing in with a browser")
    return principal


BrowserPrincipalDep = Annotated[Principal, Depends(require_browser_session)]
