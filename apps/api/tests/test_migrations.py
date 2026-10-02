"""The migrations: they apply, they reverse, and they match the models."""

import asyncio
from typing import Any

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from paritylens_api.migrate import alembic_config
from paritylens_api.models import Base
from paritylens_api.services.reports import signature_of
from sqlalchemy import Connection, inspect, text
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


# Paths as the engine writes them, chosen to include what a regular
# expression over the text gets wrong: keys containing '=', ']' and '[0]'.
ODD_PATHS = [
    "$.items[0].quantity",
    "$.items[sku=A-100].quantity",
    "$['a=b'][1]",
    "$['x[0]'].y",
    "$.k['id'='a]b=c'].z",
    "header.x-rate[0]",
    "status",
]


def test_existing_differences_get_the_signature_new_ones_would(database_url: str) -> None:
    """Found in review: the backfill was a SQL regular expression, and for
    quoted keys it disagreed with the function used for new rows. One
    finding would have shown as two, split by when it was stored."""
    url = make_url(database_url).set(database="paritylens_test_backfill")
    address = url.render_as_string(hide_password=False)
    asyncio.run(_recreate_database(address))
    config = alembic_config(address)
    command.upgrade(config, "0001")

    def insert(connection: Connection) -> None:
        # Only this table matters here; skip building its five parents.
        connection.execute(text("SET session_replication_role = replica"))
        for position, path in enumerate(ODD_PATHS):
            connection.execute(
                text(
                    "INSERT INTO differences (id, step_result_id, run_id, position, kind, path,"
                    " severity, reason, hints) VALUES (gen_random_uuid(), gen_random_uuid(),"
                    " gen_random_uuid(), :position, 'value_changed', :path, 'medium',"
                    " 'default_for_kind', '[]')"
                ),
                {"position": position, "path": path},
            )
        connection.commit()

    _in_database(address, insert)

    command.upgrade(config, "head")

    def signatures(connection: Connection) -> dict[str, str]:
        rows = connection.execute(text("SELECT path, signature FROM differences"))
        return {path: signature for path, signature in rows}

    assert _in_database(address, signatures) == {
        path: signature_of("value_changed", path) for path in ODD_PATHS
    }
