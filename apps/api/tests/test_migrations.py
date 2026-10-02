"""The migrations: they apply, they reverse, and they match the models."""

import asyncio
from typing import Any

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from paritylens_api.migrate import alembic_config
from paritylens_api.models import Base
from sqlalchemy import Connection, inspect
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from .conftest import _recreate_database


def _in_database(url: str, work: Any) -> Any:
    async def run() -> Any:
        engine = create_async_engine(url)
        async with engine.connect() as connection:
            result = await connection.run_sync(work)
        await engine.dispose()
        return result

    return asyncio.run(run())


def _table_names(connection: Connection) -> set[str]:
    return set(inspect(connection).get_table_names())


def _differences(connection: Connection) -> list[Any]:
    context = MigrationContext.configure(connection, opts={"compare_type": True})
    return list(compare_metadata(context, Base.metadata))


def test_migrations_apply_reverse_and_apply_again(database_url: str) -> None:
    # A database of its own, so the other tests keep theirs.
    url = make_url(database_url).set(database="paritylens_test_migrations")
    text = url.render_as_string(hide_password=False)
    asyncio.run(_recreate_database(text))
    config = alembic_config(text)

    command.upgrade(config, "head")
    assert "projects" in _in_database(text, _table_names)

    command.downgrade(config, "base")
    assert _in_database(text, _table_names) == {"alembic_version"}

    command.upgrade(config, "head")
    assert "differences" in _in_database(text, _table_names)


def test_the_models_and_the_migrations_describe_the_same_schema(database_url: str) -> None:
    """Fails when a model changed and nobody wrote the migration for it."""
    assert _in_database(database_url, _differences) == []
