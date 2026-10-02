"""Settings, read once from the environment.

Every value has a default that works for local development, so
`docker compose up` needs no .env file. The defaults are not safe for a
real deployment, and `Settings` refuses to load them in production.
"""

import base64
from enum import StrEnum
from functools import lru_cache
from typing import Self
from urllib.parse import urlsplit

from paritylens_engine.egress import EgressMode
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Decodes to 32 zero bytes. Good enough to run locally; `Settings` rejects
# it outside local development.
LOCAL_MASTER_KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="


class Environment(StrEnum):
    LOCAL = "local"
    PRODUCTION = "production"


class AuthMode(StrEnum):
    # Sign in by typing any email address. For local development only.
    DEV = "dev"
    GOOGLE = "google"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PARITYLENS_", env_file=".env", extra="ignore")

    environment: Environment = Environment.LOCAL
    database_url: str = "postgresql+asyncpg://paritylens:local-dev-only@localhost:5432/paritylens"

    # Where users reach the web app. Used for OAuth redirects and to check
    # the Origin header of state-changing requests.
    public_base_url: str = "http://localhost:3000"

    auth_mode: AuthMode = AuthMode.DEV
    google_client_id: str = ""
    google_client_secret: str = ""
    session_days: int = Field(default=14, ge=1, le=90)

    # Base64 of the 32-byte key that encrypts stored secrets.
    master_key: str = LOCAL_MASTER_KEY
    master_key_version: int = 1

    # What the hosted worker may connect to. See ADR 0006.
    egress_mode: EgressMode = EgressMode.PERMISSIVE
    egress_allow_hosts: str = ""  # comma-separated, for allowlist mode

    max_queued_runs_per_workspace: int = Field(default=5, ge=1)
    result_retention_days: int = Field(default=30, ge=1)

    @property
    def is_production(self) -> bool:
        return self.environment is Environment.PRODUCTION

    @property
    def allow_hosts(self) -> frozenset[str]:
        return frozenset(
            host.strip() for host in self.egress_allow_hosts.split(",") if host.strip()
        )

    @model_validator(mode="after")
    def _master_key_is_usable(self) -> Self:
        # Checked at startup in every environment. Otherwise a malformed
        # key is only discovered when the first secret is saved.
        try:
            key = base64.b64decode(self.master_key, validate=True)
        except ValueError as exc:
            raise ValueError("master_key must be base64") from exc
        if len(key) != 32:
            raise ValueError("master_key must decode to exactly 32 bytes")
        return self

    @model_validator(mode="after")
    def _local_mode_is_really_local(self) -> Self:
        # A deployment that forgets to set PARITYLENS_ENVIRONMENT would run
        # with the local defaults, development sign-in included. A real
        # deployment has a real public URL, so that gives it away.
        host = urlsplit(self.public_base_url).hostname
        if not self.is_production and host not in ("localhost", "127.0.0.1", "::1"):
            raise ValueError(
                "environment is 'local' but public_base_url is not localhost; "
                "set PARITYLENS_ENVIRONMENT=production"
            )
        return self

    @model_validator(mode="after")
    def _production_is_not_running_on_local_defaults(self) -> Self:
        if not self.is_production:
            return self
        problems = []
        if base64.b64decode(self.master_key) == bytes(32):
            problems.append("master_key is all zeros")
        if "local-dev-only" in self.database_url:
            problems.append("database_url uses the local development password")
        if self.auth_mode is AuthMode.DEV:
            problems.append("auth_mode=dev lets anyone sign in as anyone")
        if self.egress_mode is EgressMode.PERMISSIVE:
            problems.append("egress_mode=permissive lets users reach the internal network")
        if not self.public_base_url.startswith("https://"):
            problems.append("public_base_url must be https")
        if self.auth_mode is AuthMode.GOOGLE and not (
            self.google_client_id and self.google_client_secret
        ):
            problems.append("google_client_id and google_client_secret are required")
        if problems:
            raise ValueError("refusing to start in production: " + "; ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
