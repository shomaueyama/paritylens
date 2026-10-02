"""Reading the endpoints out of an OpenAPI document."""

import json
import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import yaml
from paritylens_engine.jsonvalue import printable

from paritylens_api.core.errors import InvalidRequestError
from paritylens_api.schemas.projects import MAX_PATH_TEMPLATE_BYTES

_METHODS = ("get", "post", "put", "patch", "delete", "head", "options")
MAX_ENDPOINTS = 2000


@dataclass(frozen=True)
class ImportedEndpoint:
    method: str
    path_template: str
    summary: str


def parse_document(text: str) -> dict[str, Any]:
    """Parse an OpenAPI document given as JSON or YAML text."""
    try:
        document = json.loads(text)
    except RecursionError as exc:
        raise InvalidRequestError("the document is nested too deeply") from exc
    except ValueError:
        try:
            # safe_load builds plain data only; it cannot be made to run code.
            document = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise InvalidRequestError("the document is neither valid JSON nor valid YAML") from exc
        except RecursionError as exc:
            raise InvalidRequestError("the document is nested too deeply") from exc
    if not isinstance(document, dict) or not isinstance(document.get("paths"), dict):
        raise InvalidRequestError("the document has no 'paths' object; is it OpenAPI?")
    return document


def endpoints_in(document: dict[str, Any]) -> list[ImportedEndpoint]:
    """Every method and path the document declares. Anything malformed is skipped."""
    found: list[ImportedEndpoint] = []
    for path, item in document["paths"].items():
        if not isinstance(path, str) or not path.startswith("/") or not isinstance(item, dict):
            continue
        if len(path.encode("utf-8")) > MAX_PATH_TEMPLATE_BYTES:
            raise InvalidRequestError(
                f"a path in the document is longer than {MAX_PATH_TEMPLATE_BYTES} bytes"
            )
        for method in _METHODS:
            operation = item.get(method)
            if not isinstance(operation, dict):
                continue
            summary = operation.get("summary") or operation.get("operationId") or ""
            found.append(
                ImportedEndpoint(
                    method=method.upper(),
                    path_template=path,
                    summary=str(summary)[:500],
                )
            )
            if len(found) > MAX_ENDPOINTS:
                raise InvalidRequestError(f"the document has more than {MAX_ENDPOINTS} operations")
    return found


MAX_DOCUMENT_NODES = 200_000
MAX_DOCUMENT_DEPTH = 100


def storable(document: Any) -> Any:
    """A copy of a parsed document that is safe to store as JSON.

    YAML can describe things JSON cannot: dates, binary data, infinity,
    and, through anchors, structures that refer to themselves or expand to
    billions of nodes. This walks the document once with a budget and
    turns it into plain JSON data, or refuses.
    """
    budget = [MAX_DOCUMENT_NODES]

    def convert(value: Any, depth: int) -> Any:
        budget[0] -= 1
        if budget[0] < 0 or depth > MAX_DOCUMENT_DEPTH:
            raise InvalidRequestError("the document is too large or too deeply nested")
        if value is None or isinstance(value, bool | int):
            return value
        if isinstance(value, float):
            if not math.isfinite(value):
                raise InvalidRequestError("the document contains a number that is not finite")
            return value
        if isinstance(value, str):
            return printable(value).replace("\x00", "")
        if isinstance(value, list | tuple | set | frozenset):
            return [convert(item, depth + 1) for item in value]
        if isinstance(value, dict):
            return {
                printable(str(key)).replace("\x00", ""): convert(item, depth + 1)
                for key, item in value.items()
            }
        if isinstance(value, date | datetime):
            return value.isoformat()
        raise InvalidRequestError(f"the document contains a {type(value).__name__} value")

    return convert(document, 0)
