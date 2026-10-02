from typing import Any

import httpx2
import pytest
from paritylens_cli.upload import UploadError, upload_report
from paritylens_engine.report import RunReport

REPORT = RunReport.model_validate(
    {
        "engine_version": "0.1.0",
        "started_at": "2026-10-02T00:00:00Z",
        "finished_at": "2026-10-02T00:00:01Z",
        "old_base_url": "http://old.test",
        "new_base_url": "http://new.test",
        "rules": {},
        "summary": {"total": 0, "compatible": 0, "warning": 0, "breaking": 0, "error": 0},
        "cases": [],
    }
)


def upload(handler: Any) -> str:
    return upload_report(
        REPORT,
        api_url="https://paritylens.example/",
        project_id="p-1",
        token="plk_abc",
        transport=httpx2.MockTransport(handler),
    )


def test_the_report_is_posted_to_the_project_with_the_token() -> None:
    seen: list[httpx2.Request] = []

    def server(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(201, json={"id": "run-1"})

    assert upload(server) == "run-1"

    [request] = seen
    assert str(request.url) == "https://paritylens.example/api/v1/projects/p-1/runs/import"
    assert request.headers["authorization"] == "Bearer plk_abc"
    assert RunReport.model_validate_json(request.content) == REPORT


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (401, "the API token was not accepted"),
        (404, "the project was not found"),
        (413, "too large"),
        (500, "the server answered 500"),
    ],
)
def test_a_refusal_is_explained(status: int, message: str) -> None:
    with pytest.raises(UploadError, match=message):
        upload(lambda request: httpx2.Response(status, json={}))


def test_an_unreachable_server_is_explained_without_the_token() -> None:
    def down(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused")

    with pytest.raises(UploadError) as raised:
        upload(down)

    assert "could not reach https://paritylens.example/" in str(raised.value)
    assert "plk_abc" not in str(raised.value)


def test_an_answer_that_is_not_what_was_expected_is_explained() -> None:
    with pytest.raises(UploadError, match="was not understood"):
        upload(lambda request: httpx2.Response(201, text="<html>proxy page</html>"))
