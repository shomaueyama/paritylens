"""Sending a report to a ParityLens server, to be stored and viewed there."""

import httpx2
from paritylens_engine.report import RunReport


class UploadError(Exception):
    """The report could not be uploaded. The message is for the user."""


def upload_report(
    report: RunReport,
    *,
    api_url: str,
    project_id: str,
    token: str,
    transport: httpx2.BaseTransport | None = None,
) -> str:
    """Upload a report and return the ID of the run it was stored as."""
    url = f"{api_url.rstrip('/')}/api/v1/projects/{project_id}/runs/import"
    try:
        with httpx2.Client(transport=transport, timeout=60.0) as client:
            response = client.post(
                url,
                content=report.model_dump_json(),
                headers={"authorization": f"Bearer {token}", "content-type": "application/json"},
            )
    except httpx2.HTTPError as exc:
        raise UploadError(f"could not reach {api_url}: {type(exc).__name__}") from exc

    if response.status_code == 201:
        try:
            return str(response.json()["id"])
        except (ValueError, KeyError, TypeError) as exc:
            raise UploadError("upload failed: the server's answer was not understood") from exc
    reasons = {
        401: "the API token was not accepted",
        404: "the project was not found (check its ID and the workspace of the token)",
        413: "the report is too large to upload",
    }
    reason = reasons.get(response.status_code, f"the server answered {response.status_code}")
    raise UploadError(f"upload failed: {reason}")
