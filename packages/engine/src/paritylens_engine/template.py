"""Placeholders in requests: {{order_id}} is replaced by a value captured
from an earlier response.

Each side of a comparison has its own variables. The old API's order ID is
used to query the old API, the new API's to query the new one.
"""

import json
import re
from collections.abc import Mapping
from decimal import Decimal

from pydantic import JsonValue

from paritylens_engine.jsonvalue import Json, to_plain

_PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


class MissingVariableError(KeyError):
    """A placeholder names a variable that no earlier step captured."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.name = name


def placeholders(value: JsonValue) -> set[str]:
    """Every variable name used anywhere in a value."""
    if isinstance(value, str):
        return set(_PLACEHOLDER.findall(value))
    if isinstance(value, list):
        return set().union(*(placeholders(item) for item in value))
    if isinstance(value, dict):
        return set().union(*(placeholders(key) | placeholders(item) for key, item in value.items()))
    return set()


def render_text(text: str, variables: Mapping[str, Json]) -> str:
    """Replace every placeholder in a string with the variable's text form."""

    def substitute(match: re.Match[str]) -> str:
        return _as_text(_lookup(match.group(1), variables))

    return _PLACEHOLDER.sub(substitute, text)


def render_value(value: JsonValue, variables: Mapping[str, Json]) -> JsonValue:
    """Replace placeholders throughout a JSON value.

    A string that is nothing but one placeholder becomes the variable
    itself, keeping its type: {"order_id": "{{id}}"} sends a number if a
    number was captured. Inside longer text the value is written as text.
    """
    if isinstance(value, str):
        whole = _PLACEHOLDER.fullmatch(value)
        if whole is not None:
            return to_plain(_lookup(whole.group(1), variables))
        return render_text(value, variables)
    if isinstance(value, list):
        return [render_value(item, variables) for item in value]
    if isinstance(value, dict):
        return {key: render_value(item, variables) for key, item in value.items()}
    return value


def _lookup(name: str, variables: Mapping[str, Json]) -> Json:
    if name not in variables:
        raise MissingVariableError(name)
    return variables[name]


def _as_text(value: Json) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    if isinstance(value, int | Decimal):
        return str(value)
    return json.dumps(to_plain(value), ensure_ascii=False)
