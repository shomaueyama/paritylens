"""Session and API tokens.

A token is a long random string. The server stores only its SHA-256 hash,
so a copy of the database does not let anyone sign in. A fast hash is the
right tool here, unlike for passwords: the token has 256 bits of entropy,
so there is nothing to brute-force.
"""

import hashlib
import secrets

API_TOKEN_PREFIX = "plk_"  # noqa: S105 - a label, not a credential


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def new_api_token() -> str:
    # The prefix makes a leaked token recognisable to secret scanners.
    return API_TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
