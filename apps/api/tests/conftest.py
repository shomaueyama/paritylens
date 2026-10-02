"""Fixtures for the API tests.

The tests use a real PostgreSQL database, because what is being tested is
SQL: joins that enforce ownership, constraints, JSONB columns, locking.
An in-memory substitute would test something else.

Each test runs inside a transaction that is rolled back afterwards, so
tests do not see each other's rows and there is nothing to clean up.
"""

import asyncio
import os
from collections.abc import AsyncIterator

import asyncpg
import httpx2
import pytest
from paritylens_api.core.config import Settings, get_settings
from paritylens_api.db import get_session
from paritylens_api.main import create_app
from paritylens_api.migrate import upgrade
from paritylens_api.testing import ORIGIN, MakeClient, SignIn
from sqlalchemy import NullPool
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

DEFAULT_URL = "postgresql+asyncpg://paritylens:local-dev-only@localhost:5432/paritylens_test"


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


async def _recreate_database(database_url: str) -> None:
    url = make_url(database_url)
    admin = await asyncpg.connect(
        host=url.host, port=url.port, user=url.username, password=url.password, database="postgres"
    )
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)')
        await admin.execute(f'CREATE DATABASE "{url.database}"')
    finally:
        await admin.close()


@pytest.fixture(scope="session")
def database_url() -> str:
    """A freshly created database with every migration applied.

    The schema comes from the migrations, not from the models, so the
    tests run against what a real deployment would have.
    """
    url = os.environ.get("PARITYLENS_TEST_DATABASE_URL", DEFAULT_URL)
    asyncio.run(_recreate_database(url))
    upgrade(url)
    return url


@pytest.fixture
async def connection(database_url: str) -> AsyncIterator[AsyncConnection]:
    """One connection with an open transaction that is rolled back after the test."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    async with engine.connect() as conn:
        transaction = await conn.begin()
        try:
            yield conn
        finally:
            await transaction.rollback()
    await engine.dispose()


@pytest.fixture
def sessions(connection: AsyncConnection) -> async_sessionmaker[AsyncSession]:
    """Sessions that all share the test's connection.

    create_savepoint: when code under test commits, that becomes a
    savepoint inside the test's transaction. The code behaves as usual
    and the final rollback still undoes everything.
    """
    return async_sessionmaker(
        bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]  # defaults only, no .env


@pytest.fixture
def make_client(sessions: async_sessionmaker[AsyncSession], settings: Settings) -> MakeClient:
    """Builds HTTP clients that call the app in-process, with their own cookie jar."""
    app = create_app()

    async def session_for_request() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            try:
                yield session
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    app.dependency_overrides[get_session] = session_for_request
    app.dependency_overrides[get_settings] = lambda: settings

    def make(**kwargs: object) -> httpx2.AsyncClient:
        headers = {"origin": ORIGIN} | dict(kwargs.pop("headers", {}))  # type: ignore[call-overload]
        return httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url=f"{ORIGIN}/api/v1",
            headers=headers,
            **kwargs,  # type: ignore[arg-type]
        )

    make.app = app  # type: ignore[attr-defined]
    return make


@pytest.fixture
async def anonymous(
    make_client: MakeClient,
) -> AsyncIterator[httpx2.AsyncClient]:
    async with make_client() as client:
        yield client


@pytest.fixture
async def sign_in(make_client: MakeClient) -> AsyncIterator[SignIn]:
    """`client = await sign_in("alice@example.com")`: a client with that user's session."""
    clients: list[httpx2.AsyncClient] = []

    async def signed_in(email: str) -> httpx2.AsyncClient:
        client = make_client()
        clients.append(client)
        response = await client.post("/auth/dev-login", json={"email": email})
        assert response.status_code == 204, response.text
        return client

    yield signed_in
    for client in clients:
        await client.aclose()


@pytest.fixture
async def alice(sign_in: SignIn) -> httpx2.AsyncClient:
    return await sign_in("alice@example.com")


@pytest.fixture
async def bob(sign_in: SignIn) -> httpx2.AsyncClient:
    return await sign_in("bob@example.com")
