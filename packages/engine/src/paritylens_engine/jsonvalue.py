"""JSON values as the engine sees them.

Numbers with a fractional part are parsed as Decimal, never float. Two
amounts that differ in the 17th digit are different amounts, and a float
would silently make them equal.
"""

import json
import math
import re
from decimal import Decimal
from typing import NoReturn

from pydantic import JsonValue

type Json = bool | int | Decimal | str | list[Json] | dict[str, Json] | None

# Deeper documents are refused. Real API responses stay far below this; the
# limit keeps the recursive code that walks a document within Python's stack.
MAX_DEPTH = 100

# Past this many characters a value is summarised instead of copied into a
# Difference. The full responses are kept elsewhere; a Difference only needs
# enough to show what changed.
MAX_VALUE_CHARS = 2000


class InvalidJsonError(ValueError):
    """The text is not JSON this engine is willing to compare."""


def _reject_constant(name: str) -> NoReturn:
    # NaN and Infinity are not JSON, although Python's parser accepts them.
    raise InvalidJsonError(f"{name} is not valid JSON")


def _parse_int(digits: str) -> int | Decimal:
    try:
        return int(digits)
    except ValueError:
        # Python refuses to convert integers of several thousand digits.
        # Decimal has no such limit and compares equal to the same int.
        return Decimal(digits)


_LONE_SURROGATE = re.compile("[\ud800-\udfff]")


def printable(text: str) -> str:
    """Replace lone surrogates, which JSON can carry but UTF-8 cannot.

    A body may contain "\\ud800" on its own. Python reads that without
    complaint and then fails when asked to write it out again, so such a
    character is turned back into its visible escape here.
    """
    if text.isascii() or not _LONE_SURROGATE.search(text):
        return text
    return text.encode("utf-8", "backslashreplace").decode("utf-8")


def _tidy(value: Json, depth: int) -> Json:
    if depth > MAX_DEPTH:
        raise InvalidJsonError(f"JSON is nested more than {MAX_DEPTH} levels deep")
    if isinstance(value, str):
        return printable(value)
    if isinstance(value, list):
        return [_tidy(item, depth + 1) for item in value]
    if isinstance(value, dict):
        return {printable(name): _tidy(item, depth + 1) for name, item in value.items()}
    return value


def parse_json(text: str) -> Json:
    try:
        value: Json = json.loads(
            text, parse_float=Decimal, parse_int=_parse_int, parse_constant=_reject_constant
        )
    except RecursionError as exc:
        raise InvalidJsonError("JSON is nested too deeply") from exc
    except (ValueError, ArithmeticError) as exc:
        # ArithmeticError: Decimal rejects exponents beyond its own limit.
        raise InvalidJsonError(str(exc)) from exc
    return _tidy(value, 0)


def json_type(value: Json) -> str:
    """The JSON type name of a value: object, array, string, number, boolean or null."""
    if value is None:
        return "null"
    # bool must be tested before int: in Python, True is an int.
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | Decimal):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def to_plain(value: Json) -> JsonValue:
    """Convert to a value that serialises as ordinary JSON (no Decimal)."""
    if isinstance(value, Decimal):
        as_float = float(value)
        # Keep it a number when that loses nothing; otherwise show the exact digits.
        if math.isfinite(as_float) and Decimal(repr(as_float)) == value:
            return as_float
        return str(value)
    if isinstance(value, list):
        return [to_plain(item) for item in value]
    if isinstance(value, dict):
        return {key: to_plain(item) for key, item in value.items()}
    return value


def clip(value: Json) -> JsonValue:
    """Like to_plain, but replaces a very large value with a one-line summary."""
    plain = to_plain(value)
    if isinstance(plain, str):
        plain = printable(plain)
        if len(plain) > MAX_VALUE_CHARS:
            return plain[:MAX_VALUE_CHARS] + "…"
        return plain
    if isinstance(plain, list | dict) and len(json.dumps(plain)) > MAX_VALUE_CHARS:
        if isinstance(plain, list):
            return f"<array of {len(plain)} items>"
        return f"<object with {len(plain)} fields>"
    return plain
