"""Apply database migrations: python -m paritylens_api.migrate

A container runs this before starting the API. The Alembic configuration
is built here in code, so nothing but the installed package is needed.
"""

from alembic import command
from alembic.config import Config


def alembic_config(database_url: str | None = None) -> Config:
    config = Config()
    # "package:directory": the migrations are found wherever the package
    # is installed.
    config.set_main_option("script_location", "paritylens_api:migrations")
    config.set_main_option("path_separator", "os")
    if database_url is not None:
        config.set_main_option("sqlalchemy.url", database_url)
    return config


def upgrade(database_url: str | None = None) -> None:
    command.upgrade(alembic_config(database_url), "head")


if __name__ == "__main__":
    upgrade()
