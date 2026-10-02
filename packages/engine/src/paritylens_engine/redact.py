"""Keeping credentials out of everything that is stored or printed.

A report is written to disk, uploaded, and shown on screen. Anything that
goes into one passes through a Redactor first.
"""

import json
import re
from collections.abc import Iterable, Mapping
from urllib.parse import quote, quote_plus

from pydantic import JsonValue

MASK = "[redacted]"

_SENSITIVE_HEADERS = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "x-auth-token",
        "x-amz-security-token",
    }
)
# Headers not on the list above whose name still gives them away.
_SENSITIVE_NAME = re.compile(r"token|secret|password|passwd|api[-_]?key|credential", re.IGNORECASE)


def is_sensitive_header(name: str) -> bool:
    return name.lower() in _SENSITIVE_HEADERS or _SENSITIVE_NAME.search(name) is not None


class Redactor:
    """Masks sensitive headers by name and known secret values wherever they appear."""

    def __init__(self, secrets: Iterable[str] = ()) -> None:
        self._forms: set[str] = set()
        self._ordered: list[str] = []
        for secret in secrets:
            self.add(secret)

    def add(self, secret: str) -> None:
        """Start masking another value, e.g. a token captured from a response."""
        if not secret:
            return
        # A secret does not always appear as written. In a URL it is
        # percent-encoded, in a JSON body it is escaped. Each form has
        # to be recognised or the value slips through in that context.
        self._forms.update((secret, quote(secret, safe=""), quote_plus(secret)))
        self._forms.add(json.dumps(secret)[1:-1])
        self._forms.add(json.dumps(secret, ensure_ascii=False)[1:-1])
        # Longest first, so that a secret containing another is masked whole.
        self._ordered = sorted(self._forms, key=len, reverse=True)

    def child(self) -> "Redactor":
        """A copy that can learn more secrets without affecting this one."""
        copy = Redactor()
        copy._forms = set(self._forms)
        copy._ordered = list(self._ordered)
        return copy

    def text(self, value: str) -> str:
        for secret in self._ordered:
            value = value.replace(secret, MASK)
        return value

    def value(self, value: JsonValue) -> JsonValue:
        """Mask secrets in every string of a JSON value, keys included."""
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            return [self.value(item) for item in value]
        if isinstance(value, dict):
            return {self.text(key): self.value(item) for key, item in value.items()}
        return value

    def headers(self, headers: Mapping[str, str]) -> dict[str, str]:
        return {
            name: MASK if is_sensitive_header(name) else self.text(value)
            for name, value in headers.items()
        }
