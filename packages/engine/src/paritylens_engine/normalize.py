"""Turn a raw response into something comparable.

Two responses can be byte-for-byte different and still mean the same thing:
header names differ in case, a charset parameter is spelled differently, the
JSON has different whitespace. This module removes those differences before
any comparison happens.
"""

from dataclasses import dataclass

from paritylens_engine.jsonvalue import InvalidJsonError, Json, parse_json
from paritylens_engine.model import ResponseSnapshot


@dataclass(frozen=True)
class EmptyBody:
    label = "empty"


@dataclass(frozen=True)
class JsonBody:
    value: Json
    label = "json"


@dataclass(frozen=True)
class TextBody:
    text: str
    label = "text"


type Body = EmptyBody | JsonBody | TextBody


def media_type(response: ResponseSnapshot) -> str | None:
    """The Content-Type without its parameters (charset and so on), lowercased."""
    content_type = response.headers.get("content-type")
    if content_type is None:
        return None
    return content_type.split(";", 1)[0].strip().lower() or None


def _is_json_media_type(value: str | None) -> bool:
    return value is not None and (value == "application/json" or value.endswith("+json"))


def read_body(response: ResponseSnapshot) -> Body:
    """Classify and parse the body.

    A body is read as JSON when the Content-Type says so, and also when it
    does not but the text plainly is JSON. Old APIs often serve JSON as
    text/plain; comparing that structurally is more useful than refusing to.
    """
    text = response.body
    if text is None:
        return EmptyBody()
    # A byte order mark is an encoding detail, not content.
    text = text.removeprefix("\ufeff")
    if not text.strip():
        return EmptyBody()
    if _is_json_media_type(media_type(response)) or text.lstrip()[:1] in ("{", "["):
        try:
            return JsonBody(parse_json(text))
        except InvalidJsonError:
            return TextBody(text)
    return TextBody(text)
