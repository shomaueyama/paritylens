"""Alembic's entry point: connects to the database and runs migrations."""

import asyncio

from alembic import context
from paritylens_api.core.config import get_settings
from paritylens_api.models import Base
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine

target_metadata = Base.metadata


def _database_url() -> str:
    # Tests point Alembic at their own database through this option.
    return context.config.get_main_option("sqlalchemy.url") or get_settings().database_url


def _run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def _run_online() -> None:
    engine = create_async_engine(_database_url())
    async with engine.connect() as connection:
        # Alembic itself is synchronous; run_sync lends it the connection.
        await connection.run_sync(_run)
    await engine.dispose()


def _run_offline() -> None:
    """Write the SQL to stdout instead of executing it (alembic upgrade --sql)."""
    context.configure(url=_database_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    _run_offline()
else:
    asyncio.run(_run_online())
