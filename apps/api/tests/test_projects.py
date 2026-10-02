"""Projects and the things configured on them."""

from typing import Any

import httpx2
import pytest
from paritylens_api.core.config import Settings
from paritylens_api.testing import create_project, create_test_case
from paritylens_engine.egress import EgressMode

pytestmark = pytest.mark.anyio


async def test_create_read_update_delete(alice: httpx2.AsyncClient) -> None:
    project = await create_project(alice, description="first")
    path = f"/projects/{project['id']}"

    assert (await alice.get(path)).json()["description"] == "first"

    updated = await alice.patch(path, json={"name": "Renamed"})
    assert updated.status_code == 200
    # Only what was sent changed.
    assert (updated.json()["name"], updated.json()["description"]) == ("Renamed", "first")

    assert (await alice.delete(path)).status_code == 204
    assert (await alice.get(path)).status_code == 404


@pytest.mark.parametrize(
    "overrides",
    [
        {"old_base_url": "ftp://old.test"},
        {"old_base_url": "http://admin:hunter2@old.test"},
        {"new_base_url": "not a url"},
        {"name": ""},
        {"old_headers": {"Host": "internal"}},
        {"old_headers": {"X-Note": "日本語"}},
        {"unknown_field": True},
    ],
)
async def test_invalid_projects_are_rejected(
    alice: httpx2.AsyncClient, overrides: dict[str, Any]
) -> None:
    response = await alice.post(
        "/projects",
        json={"name": "x", "old_base_url": "http://a.test", "new_base_url": "http://b.test"}
        | overrides,
    )

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    # A rejected value is never echoed back.
    assert "hunter2" not in response.text


async def test_a_hosted_deployment_refuses_urls_it_would_not_call(
    alice: httpx2.AsyncClient, settings: Settings
) -> None:
    settings.egress_mode = EgressMode.PUBLIC_ONLY

    blocked = await alice.post(
        "/projects",
        json={"name": "x", "old_base_url": "http://a.test:8080", "new_base_url": "https://b.test"},
    )
    allowed = await alice.post(
        "/projects",
        json={"name": "x", "old_base_url": "https://a.test", "new_base_url": "https://b.test"},
    )

    assert blocked.status_code == 422
    assert "port 8080 is not allowed" in blocked.json()["detail"]
    assert allowed.status_code == 201


async def test_deleting_a_project_deletes_what_belongs_to_it(alice: httpx2.AsyncClient) -> None:
    project = await create_project(alice)
    case = await create_test_case(alice, project["id"])

    await alice.delete(f"/projects/{project['id']}")

    assert (await alice.get(f"/test-cases/{case['id']}")).status_code == 404


# --- endpoints -------------------------------------------------------------------


async def test_an_endpoint_can_be_registered_once(alice: httpx2.AsyncClient) -> None:
    project = await create_project(alice)
    path = f"/projects/{project['id']}/endpoints"
    body = {"method": "get", "path_template": "/orders/{id}", "summary": "Fetch an order"}

    first = await alice.post(path, json=body)
    second = await alice.post(path, json=body)

    assert first.status_code == 201
    assert (first.json()["method"], first.json()["source"]) == ("GET", "manual")
    assert second.status_code == 409


OPENAPI_JSON = """
{"openapi": "3.1.0", "paths": {
  "/orders": {"get": {"summary": "List orders"}, "post": {"operationId": "createOrder"}},
  "/orders/{id}": {"get": {}, "delete": {"summary": "Cancel"}, "parameters": []}
}}
"""
OPENAPI_YAML = """
openapi: 3.1.0
paths:
  /orders:
    get: { summary: List orders }
  /customers:
    get: { summary: List customers }
"""


async def test_importing_openapi_registers_every_operation(alice: httpx2.AsyncClient) -> None:
    project = await create_project(alice)

    response = await alice.post(
        f"/projects/{project['id']}/openapi", json={"document": OPENAPI_JSON}
    )

    result = response.json()
    assert (result["created"], result["already_present"]) == (4, 0)
    assert {(e["method"], e["path_template"], e["summary"]) for e in result["endpoints"]} == {
        ("GET", "/orders", "List orders"),
        ("POST", "/orders", "createOrder"),
        ("GET", "/orders/{id}", ""),
        ("DELETE", "/orders/{id}", "Cancel"),
    }
    assert (await alice.get(f"/projects/{project['id']}")).json()["has_openapi_spec"] is True


async def test_importing_again_adds_only_what_is_new(alice: httpx2.AsyncClient) -> None:
    project = await create_project(alice)
    path = f"/projects/{project['id']}/openapi"
    await alice.post(path, json={"document": OPENAPI_JSON})

    again = (await alice.post(path, json={"document": OPENAPI_YAML})).json()

    assert (again["created"], again["already_present"]) == (1, 1)
    assert len(again["endpoints"]) == 5


@pytest.mark.parametrize(
    "document", ["not: [valid", '{"info": {}}', "just a string", "- a\n- list\n", "[1, 2]"]
)
async def test_a_document_that_is_not_openapi_is_rejected(
    alice: httpx2.AsyncClient, document: str
) -> None:
    project = await create_project(alice)

    response = await alice.post(f"/projects/{project['id']}/openapi", json={"document": document})

    assert response.status_code == 422


async def test_yaml_in_an_import_cannot_construct_objects(alice: httpx2.AsyncClient) -> None:
    project = await create_project(alice)
    document = "paths: !!python/object/apply:os.system ['echo unsafe']"

    response = await alice.post(f"/projects/{project['id']}/openapi", json={"document": document})

    assert response.status_code == 422


# --- rules -----------------------------------------------------------------------


async def test_rules_can_be_added_listed_and_removed(alice: httpx2.AsyncClient) -> None:
    project = await create_project(alice)
    path = f"/projects/{project['id']}/rules"

    await alice.post(path, json={"kind": "ignore", "path": "$..request_id"})
    unordered = await alice.post(path, json={"kind": "unordered", "path": "$.items", "key": "sku"})
    await alice.post(path, json={"kind": "compare_header", "path": "ETag"})

    rules = (await alice.get(path)).json()
    assert [(r["kind"], r["path"], r["options"]) for r in rules] == [
        ("ignore", "$..request_id", {}),
        ("unordered", "$.items", {"key": "sku"}),
        ("compare_header", "etag", {}),
    ]

    assert (await alice.delete(f"/rules/{unordered.json()['id']}")).status_code == 204
    assert len((await alice.get(path)).json()) == 2


@pytest.mark.parametrize(
    "rule",
    [
        {"kind": "ignore", "path": "$[oops"},
        {"kind": "critical", "path": ""},
        {"kind": "ignore", "path": "$.a", "key": "sku"},
        {"kind": "compare_header", "path": "not a header"},
        {"kind": "made_up", "path": "$.a"},
    ],
)
async def test_a_rule_the_engine_would_not_accept_is_rejected_when_saved(
    alice: httpx2.AsyncClient, rule: dict[str, str]
) -> None:
    project = await create_project(alice)

    response = await alice.post(f"/projects/{project['id']}/rules", json=rule)

    assert response.status_code == 422


# --- test cases ------------------------------------------------------------------


async def test_a_test_case_round_trips(alice: httpx2.AsyncClient) -> None:
    project = await create_project(alice)
    steps = [
        {
            "id": "create",
            "request": {"method": "POST", "path": "/orders", "json": {"name": "John"}},
            "capture": {"order_id": {"path": "$.id"}},
        },
        {"id": "fetch", "request": {"method": "GET", "path": "/orders/{{order_id}}"}},
    ]

    case = await create_test_case(alice, project["id"], name="Create then fetch", steps=steps)

    stored = (await alice.get(f"/test-cases/{case['id']}")).json()
    assert stored["steps"] == steps
    assert (stored["noise_detection"], stored["enabled"]) == (True, True)


async def test_a_test_case_can_be_replaced(alice: httpx2.AsyncClient) -> None:
    project = await create_project(alice)
    case = await create_test_case(alice, project["id"])

    response = await alice.put(
        f"/test-cases/{case['id']}",
        json={
            "name": "Renamed",
            "enabled": False,
            "steps": [{"request": {"method": "DELETE", "path": "/orders/1"}}],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["name"], body["enabled"]) == ("Renamed", False)
    assert body["steps"][0]["request"]["method"] == "DELETE"


@pytest.mark.parametrize(
    "steps",
    [
        [],
        [{"request": {"method": "GET", "path": "orders"}}],
        [{"request": {"method": "GET", "path": "/orders/{{order_id}}"}}],
        [{"request": {"method": "GET", "path": "/a?b=c"}}],
        [{"request": {"method": "GET", "path": "/a"}, "capture": {"v": "$.items[*].id"}}],
        [{"request": {"method": "GET", "path": "/a", "headers": {"Host": "x"}}}],
    ],
)
async def test_a_test_case_the_engine_would_not_accept_is_rejected_when_saved(
    alice: httpx2.AsyncClient, steps: list[Any]
) -> None:
    project = await create_project(alice)

    response = await alice.post(
        f"/projects/{project['id']}/test-cases", json={"name": "x", "steps": steps}
    )

    assert response.status_code == 422


async def test_a_test_case_can_be_grouped_under_an_endpoint_of_the_same_project(
    alice: httpx2.AsyncClient,
) -> None:
    project = await create_project(alice)
    other = await create_project(alice, name="Other")
    endpoint = (
        await alice.post(
            f"/projects/{project['id']}/endpoints", json={"method": "GET", "path_template": "/o"}
        )
    ).json()

    same = await alice.post(
        f"/projects/{project['id']}/test-cases",
        json={
            "name": "a",
            "endpoint_id": endpoint["id"],
            "steps": [{"request": {"method": "GET", "path": "/o"}}],
        },
    )
    different = await alice.post(
        f"/projects/{other['id']}/test-cases",
        json={
            "name": "b",
            "endpoint_id": endpoint["id"],
            "steps": [{"request": {"method": "GET", "path": "/o"}}],
        },
    )

    assert same.status_code == 201
    assert different.status_code == 422
