"""Builders for tests, here and in the packages that use the engine."""

import json
from typing import Any

from paritylens_engine.model import ResponseSnapshot


def json_response(body: Any, status: int = 200) -> ResponseSnapshot:
    return ResponseSnapshot(
        status=status,
        headers={"content-type": "application/json"},
        body=json.dumps(body),
    )


def text_response(
    body: str | None, status: int = 200, content_type: str | None = "text/plain"
) -> ResponseSnapshot:
    headers = {"content-type": content_type} if content_type else {}
    return ResponseSnapshot(status=status, headers=headers, body=body)
