"""Fixtures shared by every package's tests."""

import socket
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Any

import pytest
import uvicorn

type Serve = Callable[[Any], AbstractContextManager[str]]


@contextmanager
def _serve(app: Any) -> Iterator[str]:
    """Run an ASGI app on a real local port for the duration of the block."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))  # port 0: let the OS pick a free one
    port = listener.getsockname()[1]

    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("test server did not start")
        time.sleep(0.01)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()


@pytest.fixture
def serve() -> Serve:
    """Start an ASGI app on localhost: `with serve(app) as base_url:`."""
    return _serve
