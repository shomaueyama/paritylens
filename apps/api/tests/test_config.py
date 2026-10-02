import pytest
from paritylens_api.core.config import Settings
from pydantic import ValidationError

PRODUCTION = {
    "environment": "production",
    "auth_mode": "google",
    "google_client_id": "id",
    "google_client_secret": "secret",
    "master_key": "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE=",
    "egress_mode": "allowlist",
    "public_base_url": "https://paritylens.example",
    "database_url": "postgresql+asyncpg://app:a-real-password@db.internal:5432/paritylens",
}


def build(**overrides: str) -> Settings:
    return Settings(_env_file=None, **(PRODUCTION | overrides))  # type: ignore[arg-type, call-arg]


def test_the_defaults_work_locally() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert not settings.is_production
    assert settings.allow_hosts == frozenset()


def test_a_complete_production_configuration_loads() -> None:
    assert build().is_production


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"auth_mode": "dev"}, "lets anyone sign in as anyone"),
        (
            {"master_key": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="},
            "master_key is all zeros",
        ),
        ({"egress_mode": "permissive"}, "reach the internal network"),
        ({"public_base_url": "http://paritylens.example"}, "must be https"),
        ({"google_client_secret": ""}, "google_client_secret are required"),
    ],
)
def test_production_refuses_to_start_on_a_local_default(
    override: dict[str, str], reason: str
) -> None:
    with pytest.raises(ValidationError, match=reason):
        build(**override)


def test_allow_hosts_are_split_and_trimmed() -> None:
    settings = build(egress_allow_hosts=" legacy-shop-api:8000, modern-shop-api:8000 ,")

    assert settings.allow_hosts == {"legacy-shop-api:8000", "modern-shop-api:8000"}


# --- found in review ----------------------------------------------------------------


@pytest.mark.parametrize("key", ["not base64 at all", "c2hvcnQ=", ""])
def test_an_unusable_master_key_is_rejected_at_startup_in_any_environment(key: str) -> None:
    """Not when the first secret is saved."""
    with pytest.raises(ValidationError, match="master_key"):
        Settings(_env_file=None, master_key=key)  # type: ignore[call-arg]


def test_the_zero_key_is_refused_in_production_however_it_is_spelled() -> None:
    # Decodes to the same 32 zero bytes as the local default.
    with pytest.raises(ValidationError, match="all zeros"):
        build(master_key="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB=")


def test_production_refuses_the_local_database_password() -> None:
    with pytest.raises(ValidationError, match="local development password"):
        build(database_url="postgresql+asyncpg://paritylens:local-dev-only@db:5432/paritylens")


def test_a_deployment_that_forgot_to_say_production_does_not_start() -> None:
    """Otherwise it would run with development sign-in on a public address."""
    with pytest.raises(ValidationError, match="set PARITYLENS_ENVIRONMENT=production"):
        Settings(_env_file=None, public_base_url="https://paritylens.example")  # type: ignore[call-arg]
