"""ASGI middleware: request size limits and the request log.

Both are written as plain ASGI callables instead of with Starlette's
@app.middleware("http") helper. That helper runs the application in a
separate task and stands between it and `receive`, which changes how an
exception raised while reading the body travels; plain middleware does
not get in the way.

Limits on request size are enforced before anything reads the body.

FastAPI reads and parses a request body before the handler runs, and
before authentication. Without a limit, anyone can make the server read
and parse as much as they care to send.
"""

import logging
import time
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from fastapi import HTTPException

from paritylens_api.core.errors import problem

type Scope = MutableMapping[str, Any]
type Message = MutableMapping[str, Any]
type Receive = Callable[[], Awaitable[Message]]
type Send = Callable[[Message], Awaitable[None]]
type AsgiApp = Callable[[Scope, Receive, Send], Awaitable[None]]

DEFAULT_MAX_BYTES = 256 * 1024
MAX_REPORT_BYTES = 32 * 1024 * 1024
# The document is a JSON string of at most 1 MiB; escaping can double it.
MAX_OPENAPI_BYTES = 3 * 1024 * 1024


def limit_for(path: str) -> int:
    if path.endswith("/runs/import"):
        return MAX_REPORT_BYTES
    if path.endswith("/openapi"):
        return MAX_OPENAPI_BYTES
    return DEFAULT_MAX_BYTES


class BodySizeLimitMiddleware:
    """Refuses requests whose body is larger than the route allows.

    A declared Content-Length over the limit is refused without reading
    anything. A body sent without one (chunked) is counted as it streams
    in and cut off at the limit.
    """

    def __init__(self, app: AsgiApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit = limit_for(scope["path"])
        headers = dict(scope["headers"])
        declared = headers.get(b"content-length", b"")
        if declared.isdigit() and int(declared) > limit:
            await problem(413, "Content Too Large", f"the body may be at most {limit} bytes")(
                scope, receive, send
            )
            return

        received = 0

        async def counting_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    # FastAPI's own HTTPException: its body parsing lets that
                    # one through and turns any other error into a 400.
                    raise HTTPException(413, f"the body may be at most {limit} bytes")
            return message

        await self.app(scope, counting_receive, send)


logger = logging.getLogger("paritylens.api")


class RequestLogMiddleware:
    """Logs one line per request: method, route, status, duration."""

    def __init__(self, app: AsgiApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        status = 500  # what the client gets if the application raises

        async def recording_send(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, recording_send)
        finally:
            route = scope.get("route")
            logger.info(
                "request",
                extra={
                    "method": scope["method"],
                    # The route template (/projects/{project_id}), not the
                    # URL: no IDs, and above all no query string.
                    "route": getattr(route, "path", "unmatched"),
                    "status": status,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                },
            )
