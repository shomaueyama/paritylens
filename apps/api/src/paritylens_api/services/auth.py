"""Signing in: users, their workspace, and sessions."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from paritylens_api.core.security import hash_token, new_session_token
from paritylens_api.models import Session, User, Workspace, WorkspaceMember

MAX_NAME_CHARS = 150


async def find_or_create_user(
    session: AsyncSession, *, email: str, name: str = "", google_sub: str | None = None
) -> User:
    """Find the account for a sign-in, creating it and its workspace the first time.

    A Google account is recognised by its `sub`, which never changes. Email
    is only used to adopt an account that has no Google identity yet.
    """
    email = email.strip().lower()
    # The name comes from the identity provider. Keep it storable.
    name = name.replace("\x00", "").strip()[:MAX_NAME_CHARS]

    user: User | None = None
    if google_sub is not None:
        user = await session.scalar(select(User).where(User.google_sub == google_sub))
    if user is None:
        user = await session.scalar(select(User).where(User.email == email))
        if user is not None and google_sub is not None:
            if user.google_sub is not None:
                # The address is taken by a different Google account. Do not
                # merge: whoever controls an email address today is not
                # necessarily who created the account.
                raise ValueError("this email address belongs to another account")
            user.google_sub = google_sub

    if user is None:
        user = await _create_user(session, email=email, name=name, google_sub=google_sub)
    elif name and not user.name:
        user.name = name
    await session.flush()
    return user


async def _create_user(
    session: AsyncSession, *, email: str, name: str, google_sub: str | None
) -> User:
    # ON CONFLICT DO NOTHING: when two first sign-ins for one address
    # arrive together, one inserts and the other finds the row already
    # there. Checking first and inserting second would let both insert.
    inserted = await session.scalar(
        insert(User)
        .values(id=uuid.uuid4(), email=email, name=name, google_sub=google_sub)
        .on_conflict_do_nothing(index_elements=["email"])
        .returning(User.id)
    )
    user = await session.scalar(select(User).where(User.email == email))
    if user is None:  # only if the row vanished in between
        raise ValueError("the account could not be created")
    if inserted is not None:
        # Only the request that created the user creates the workspace.
        workspace = Workspace(name=f"{name or email.split('@')[0]}'s workspace"[:200])
        session.add(workspace)
        await session.flush()
        session.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
    return user


async def start_session(session: AsyncSession, user: User, *, days: int) -> tuple[str, datetime]:
    """Create a session. Returns the token for the cookie and when it expires."""
    token = new_session_token()
    expires_at = datetime.now(UTC) + timedelta(days=days)
    session.add(Session(user_id=user.id, token_hash=hash_token(token), expires_at=expires_at))
    await session.flush()
    return token, expires_at


async def end_session(session: AsyncSession, token: str) -> None:
    await session.execute(delete(Session).where(Session.token_hash == hash_token(token)))
