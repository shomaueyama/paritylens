"""Structured logs: one JSON object per line.

What is logged is chosen deliberately: identifiers, counts, durations,
outcomes. Never request or response bodies, header values, query strings
or email addresses. Call sites pass named fields, and only the fields
passed are written, so nothing reaches a log by accident.
"""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

_RESERVED = frozenset(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": record.getMessage(),
        }
        # Fields passed as logger.info("event", extra={...}).
        entry.update({key: value for key, value in record.__dict__.items() if key not in _RESERVED})
        if record.exc_info and record.exc_info[0] is not None:
            # The exception's type, not its message: messages quote inputs.
            entry["error_type"] = record.exc_info[0].__name__
        return json.dumps(entry, default=str)


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    # uvicorn installs its own handlers, which print full tracebacks. Route
    # its loggers through ours instead, so an unhandled error is recorded
    # by type and nothing it was carrying is printed.
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = [handler]
        uvicorn_logger.propagate = False
    # uvicorn's access log includes the query string; ours does not.
    logging.getLogger("uvicorn.access").disabled = True
    # The HTTP client logs every request URL at INFO.
    for noisy in ("httpx2", "httpcore2"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
