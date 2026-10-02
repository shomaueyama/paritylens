"""Database engine and sessions.

One engine (a connection pool) per process. One session per request: a
session is a unit of work that collects changes and writes them together
on commit, like a DbContext in Entity Framework.
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from paritylens_api.core.config import get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        # pool_pre_ping: test a pooled connection before using it, so a
        # database restart costs one reconnect instead of one failed request.
        # hide_parameters: a database error must not print the values of the
        # statement that failed. They are user data, and can be credentials.
        _engine = create_async_engine(
            get_settings().database_url, pool_pre_ping=True, hide_parameters=True
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        # expire_on_commit=False: objects stay readable after commit. With
        # async there is no lazy reload to fall back on.
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: a session that commits if the request succeeds.

    Everything a request does to the database is one transaction. If the
    handler raises, nothing it wrote is kept.

    It is used with scope="function" (see deps.SessionDep), which makes the
    commit happen before the response is sent. With the default scope the
    client would be told "201 Created" first and the commit would run
    afterwards, where its failure could no longer be reported.
    """
    async with get_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise
