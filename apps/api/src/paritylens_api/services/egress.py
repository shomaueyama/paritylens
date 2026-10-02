"""The egress policy this deployment runs with."""

from paritylens_engine.egress import EgressDeniedError, EgressPolicy

from paritylens_api.core.config import Settings
from paritylens_api.core.errors import InvalidRequestError


def egress_policy(settings: Settings) -> EgressPolicy:
    return EgressPolicy(mode=settings.egress_mode, allow_hosts=settings.allow_hosts)


def check_targets(settings: Settings, *urls: str | None) -> None:
    """Reject a base URL this deployment would refuse to call anyway.

    This is a courtesy, not the defence: the address is checked again at
    connection time, when what the name resolves to is known.
    """
    policy = egress_policy(settings)
    for url in urls:
        if url is None:
            continue
        try:
            policy.check_url(url)
        except EgressDeniedError as exc:
            raise InvalidRequestError(f"this deployment cannot call that URL: {exc}") from exc
