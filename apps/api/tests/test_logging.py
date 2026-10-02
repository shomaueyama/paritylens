import json
import logging

from paritylens_api.core.logging import JsonFormatter


def record(message: str, **extra: object) -> logging.LogRecord:
    made = logging.makeLogRecord({"name": "paritylens.test", "levelname": "INFO", "msg": message})
    made.__dict__.update(extra)
    return made


def test_a_log_line_is_one_json_object_with_the_fields_that_were_passed() -> None:
    line = JsonFormatter().format(record("run completed", run_id="abc", duration_ms=1200))

    entry = json.loads(line)
    assert entry["event"] == "run completed"
    assert (entry["run_id"], entry["duration_ms"]) == ("abc", 1200)
    assert entry["level"] == "info"
    assert "\n" not in line


def test_an_exception_is_logged_by_type_without_its_message() -> None:
    """Exception messages quote inputs: URLs, header values, SQL parameters."""
    try:
        raise RuntimeError("failed calling https://api.test/?token=s3cr3t")
    except RuntimeError:
        import sys

        failed = record("run failed", run_id="abc")
        failed.exc_info = sys.exc_info()

    line = JsonFormatter().format(failed)

    assert json.loads(line)["error_type"] == "RuntimeError"
    assert "s3cr3t" not in line
