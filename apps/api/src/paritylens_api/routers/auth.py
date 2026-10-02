"""Signing in and out."""

import asyncio
import hashlib
from datetime import datetime
from typing import Annotated

import httpx2
import jwt
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from paritylens_api.core.config import AuthMode, Settings
from paritylens_api.core.errors import NotFoundError
from paritylens_api.deps import (
    SESSION_COOKIE,
    PrincipalDep,
    SessionDep,
    SettingsDep,
    check_origin,
)
from paritylens_api.models import User, Workspace
from paritylens_api.schemas.auth import AuthConfig, DevLogin, Me
from paritylens_api.services import google
from paritylens_api.services.auth import end_session, find_or_create_user, start_session

router = APIRouter(tags=["auth"])

_AUTH_PATH = "/api/v1/auth"


def get_key_resolver() -> google.KeyResolver:
    return google.google_key_resolver()


def get_http_client() -> httpx2.AsyncClient:
    return httpx2.AsyncClient(timeout=10.0, trust_env=False)


def _set_session_cookie(
    response: Response, token: str, expires_at: datetime, settings: Settings
) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        expires=expires_at,
        # HttpOnly: page scripts cannot read it, so an XSS bug cannot steal it.
        httponly=True,
        # Secure: never sent over plain HTTP. Off only for http://localhost.
        secure=settings.public_base_url.startswith("https://"),
        # Lax: not sent on cross-site POSTs, which blocks most CSRF.
        samesite="lax",
        path="/",
    )


def _flow_key(settings: Settings) -> bytes:
    # Derived from the master key and never used for anything else.
    return hashlib.sha256(b"oauth-flow-key:" + settings.master_key.encode("ascii")).digest()


def _redirect_uri(settings: Settings) -> str:
    return f"{settings.public_base_url.rstrip('/')}{_AUTH_PATH}/google/callback"


@router.get("/auth/config")
async def auth_config(settings: SettingsDep) -> AuthConfig:
    """Which way of signing in this deployment offers."""
    return AuthConfig(mode=settings.auth_mode)


@router.post("/auth/dev-login", status_code=204)
async def dev_login(
    body: DevLogin, request: Request, response: Response, session: SessionDep, settings: SettingsDep
) -> None:
    """Sign in as any email address. Exists only when auth_mode is dev."""
    if settings.auth_mode is not AuthMode.DEV:
        raise NotFoundError()
    check_origin(request, settings)
    user = await find_or_create_user(session, email=body.email)
    token, expires_at = await start_session(session, user, days=settings.session_days)
    _set_session_cookie(response, token, expires_at, settings)


@router.get("/auth/google/login")
async def google_login(settings: SettingsDep) -> RedirectResponse:
    if settings.auth_mode is not AuthMode.GOOGLE:
        raise NotFoundError()
    flow = google.Flow.start()
    response = RedirectResponse(
        google.authorization_url(
            flow, client_id=settings.google_client_id, redirect_uri=_redirect_uri(settings)
        ),
        status_code=302,
    )
    response.set_cookie(
        google.FLOW_COOKIE,
        google.seal_flow(flow, _flow_key(settings)),
        max_age=google.FLOW_LIFETIME_SECONDS,
        httponly=True,
        secure=settings.public_base_url.startswith("https://"),
        samesite="lax",
        path=_AUTH_PATH,
    )
    return response


@router.get("/auth/google/callback")
async def google_callback(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    key_for: Annotated[google.KeyResolver, Depends(get_key_resolver)],
    client: Annotated[httpx2.AsyncClient, Depends(get_http_client)],
    code: str = "",
    state: str = "",
) -> RedirectResponse:
    if settings.auth_mode is not AuthMode.GOOGLE:
        raise NotFoundError()
    home = settings.public_base_url.rstrip("/")
    try:
        flow = google.open_flow(request.cookies.get(google.FLOW_COOKIE, ""), _flow_key(settings))
        if not code or state != flow.state:
            raise google.OAuthError("the sign-in attempt could not be verified; start again")
        async with client:
            id_token = await google.exchange_code(
                client,
                code=code,
                flow=flow,
                client_id=settings.google_client_id,
                client_secret=settings.google_client_secret,
                redirect_uri=_redirect_uri(settings),
            )
        # Looking up the signing key may fetch Google's key set over the
        # network with a blocking call. to_thread keeps that off the event
        # loop, where it would stall every other request.
        signing_key = await asyncio.to_thread(key_for, id_token)
        identity = google.verify_id_token(
            id_token,
            flow=flow,
            client_id=settings.google_client_id,
            key_for=lambda _: signing_key,
        )
        user = await find_or_create_user(
            session, email=identity.email, name=identity.name, google_sub=identity.sub
        )
    except (google.OAuthError, ValueError, jwt.PyJWTError):
        # Back to the login page with a fixed code. The reason is not put
        # in the URL: it would end up in browser history and logs.
        response = RedirectResponse(f"{home}/login?error=sign_in_failed", status_code=302)
        response.delete_cookie(google.FLOW_COOKIE, path=_AUTH_PATH)
        return response

    token, expires_at = await start_session(session, user, days=settings.session_days)
    response = RedirectResponse(f"{home}/projects", status_code=302)
    _set_session_cookie(response, token, expires_at, settings)
    response.delete_cookie(google.FLOW_COOKIE, path=_AUTH_PATH)
    return response


@router.post("/auth/logout", status_code=204)
async def logout(
    request: Request, response: Response, session: SessionDep, settings: SettingsDep
) -> None:
    check_origin(request, settings)
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        await end_session(session, token)
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me")
async def me(principal: PrincipalDep, session: SessionDep) -> Me:
    user = await session.scalar(select(User).where(User.id == principal.user_id))
    workspace = await session.scalar(
        select(Workspace).where(Workspace.id == principal.workspace_id)
    )
    if user is None or workspace is None:
        raise NotFoundError()
    return Me(
        user_id=user.id,
        email=user.email,
        name=user.name,
        workspace_id=workspace.id,
        workspace_name=workspace.name,
    )
