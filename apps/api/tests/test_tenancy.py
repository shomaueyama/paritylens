"""Tenant isolation: one workspace cannot see or touch another's data.

Alice creates one of everything. Bob, signed in to his own workspace,
then tries every route in the API with Alice's IDs. Every attempt must
answer 404, the same answer as for an ID that does not exist.

The list of routes is not written by hand. It is read from the running
application, so a route added later is covered automatically, and the
test fails if it does not know how to fill in one of the route's IDs.
"""

import re
import uuid
from typing import Any

import httpx2
import pytest
from paritylens_api.testing import MakeClient, create_project, create_test_case

pytestmark = pytest.mark.anyio

# Routes that take no ID belonging to a workspace.
NOT_OWNED = {"/api/v1/api-tokens/{token_id}"}  # covered in test_auth.py

REPORT: dict[str, Any] = {
    "engine_version": "0.1.0",
    "started_at": "2026-10-02T00:00:00Z",
    "finished_at": "2026-10-02T00:00:01Z",
    "old_base_url": "http://old.test",
    "new_base_url": "http://new.test",
    "rules": {},
    "summary": {"total": 1, "compatible": 0, "warning": 0, "breaking": 1, "error": 0},
    "cases": [
        {
            "name": "List orders",
            "verdict": "breaking",
            "max_severity": "high",
            "steps": [
                {
                    "id": "step-1",
                    "outcome": "compared",
                    "old": {"response": {"status": 200, "body": '{"a": 1}'}},
                    "new": {"response": {"status": 200, "body": "{}"}},
                    "comparison": {
                        "differences": [
                            {
                                "kind": "field_removed",
                                "path": "$.a",
                                "old": 1,
                                "severity": "high",
                                "reason": "default_for_kind",
                            }
                        ]
                    },
                }
            ],
        }
    ],
}


async def everything_alice_owns(alice: httpx2.AsyncClient) -> dict[str, str]:
    """Create one of each resource and return the IDs, keyed by path parameter name."""
    project = await create_project(alice)
    project_id = project["id"]
    endpoint = await alice.post(
        f"/projects/{project_id}/endpoints", json={"method": "GET", "path_template": "/orders"}
    )
    rule = await alice.post(
        f"/projects/{project_id}/rules", json={"kind": "ignore", "path": "$.id"}
    )
    await alice.put(f"/projects/{project_id}/secrets/SHOP_TOKEN", json={"value": "s3cr3t"})
    case = await create_test_case(alice, project_id)
    run = await alice.post(f"/projects/{project_id}/runs/import", json=REPORT)
    assert run.status_code == 201, run.text
    detail = (await alice.get(f"/runs/{run.json()['id']}")).json()
    return {
        "project_id": project_id,
        "endpoint_id": endpoint.json()["id"],
        "rule_id": rule.json()["id"],
        "name": "SHOP_TOKEN",
        "test_case_id": case["id"],
        "run_id": run.json()["id"],
        "case_result_id": detail["cases"][0]["id"],
    }


def owned_routes(app: Any) -> list[tuple[str, str]]:
    """(method, path template) for every route that has an ID in its path.

    Read from the OpenAPI document the app generates, which lists every
    route however the routers are nested.
    """
    return [
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        if "{" in path and path not in NOT_OWNED
        for method in operations
    ]


# A body that passes validation for each route that needs one. Ownership
# is checked after validation, so an invalid body would answer 422 and
# prove nothing.
BODIES: dict[tuple[str, str], Any] = {
    ("PATCH", "/api/v1/projects/{project_id}"): {"name": "stolen"},
    ("POST", "/api/v1/projects/{project_id}/endpoints"): {"method": "GET", "path_template": "/x"},
    ("POST", "/api/v1/projects/{project_id}/openapi"): {"document": '{"paths": {}}'},
    ("POST", "/api/v1/projects/{project_id}/rules"): {"kind": "ignore", "path": "$.x"},
    ("PUT", "/api/v1/projects/{project_id}/secrets/{name}"): {"value": "overwritten"},
    ("POST", "/api/v1/projects/{project_id}/test-cases"): {
        "name": "x",
        "steps": [{"request": {"method": "GET", "path": "/"}}],
    },
    ("PUT", "/api/v1/test-cases/{test_case_id}"): {
        "name": "x",
        "steps": [{"request": {"method": "GET", "path": "/"}}],
    },
    ("POST", "/api/v1/projects/{project_id}/runs/import"): REPORT,
}


async def test_every_route_answers_404_for_another_workspaces_ids(
    alice: httpx2.AsyncClient, bob: httpx2.AsyncClient, make_client: MakeClient
) -> None:
    ids = await everything_alice_owns(alice)
    routes = owned_routes(make_client.app)  # type: ignore[attr-defined]
    assert len(routes) >= 20  # the app really was inspected

    for method, template in routes:
        path = re.sub(r"\{(\w+)\}", lambda match: ids[match.group(1)], template)
        path = path.removeprefix("/api/v1")
        body = BODIES.get((method, template))

        response = await bob.request(method, path, json=body)

        assert response.status_code == 404, f"{method} {template} answered {response.status_code}"


async def test_another_workspaces_id_looks_exactly_like_one_that_does_not_exist(
    alice: httpx2.AsyncClient, bob: httpx2.AsyncClient
) -> None:
    project = await create_project(alice)

    theirs = await bob.get(f"/projects/{project['id']}")
    nobodys = await bob.get(f"/projects/{uuid.uuid4()}")

    assert (theirs.status_code, theirs.json()) == (nobodys.status_code, nobodys.json())


async def test_nothing_of_alices_was_changed_by_bobs_attempts(
    alice: httpx2.AsyncClient, bob: httpx2.AsyncClient, make_client: MakeClient
) -> None:
    ids = await everything_alice_owns(alice)
    routes = owned_routes(make_client.app)  # type: ignore[attr-defined]
    assert len(routes) >= 20
    for method, template in routes:
        path = re.sub(r"\{(\w+)\}", lambda match: ids[match.group(1)], template)
        await bob.request(method, path.removeprefix("/api/v1"), json=BODIES.get((method, template)))

    project_id = ids["project_id"]
    assert (await alice.get(f"/projects/{project_id}")).json()["name"] == "Shop API migration"
    assert len((await alice.get(f"/projects/{project_id}/endpoints")).json()) == 1
    assert len((await alice.get(f"/projects/{project_id}/rules")).json()) == 1
    assert len((await alice.get(f"/projects/{project_id}/test-cases")).json()) == 1
    assert len((await alice.get(f"/projects/{project_id}/runs")).json()["runs"]) == 1


async def test_lists_show_only_the_callers_own_projects(
    alice: httpx2.AsyncClient, bob: httpx2.AsyncClient
) -> None:
    await create_project(alice, name="Alice's")
    await create_project(bob, name="Bob's")

    assert [p["name"] for p in (await alice.get("/projects")).json()] == ["Alice's"]
    assert [p["name"] for p in (await bob.get("/projects")).json()] == ["Bob's"]


async def test_a_test_case_cannot_point_at_another_workspaces_endpoint(
    alice: httpx2.AsyncClient, bob: httpx2.AsyncClient
) -> None:
    ids = await everything_alice_owns(alice)
    bobs_project = await create_project(bob)

    response = await bob.post(
        f"/projects/{bobs_project['id']}/test-cases",
        json={
            "name": "x",
            "endpoint_id": ids["endpoint_id"],
            "steps": [{"request": {"method": "GET", "path": "/"}}],
        },
    )

    assert response.status_code == 404
