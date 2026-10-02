"""Helpers for the API tests: sample data and small request shortcuts."""

from collections.abc import Awaitable, Callable
from typing import Any

import httpx2

# The origin the tests pretend the browser is on; matches the default settings.
ORIGIN = "http://localhost:3000"

# `client = await sign_in("alice@example.com")`
type SignIn = Callable[[str], Awaitable[httpx2.AsyncClient]]
type MakeClient = Callable[..., httpx2.AsyncClient]

PROJECT: dict[str, Any] = {
    "name": "Shop API migration",
    "old_base_url": "http://old.test",
    "new_base_url": "http://new.test",
}
GET_ORDERS: dict[str, Any] = {
    "name": "List orders",
    "steps": [{"request": {"method": "GET", "path": "/orders"}}],
}


async def create_project(client: httpx2.AsyncClient, **overrides: Any) -> dict[str, Any]:
    response = await client.post("/projects", json=PROJECT | overrides)
    assert response.status_code == 201, response.text  # noqa: S101
    project: dict[str, Any] = response.json()
    return project


async def create_test_case(
    client: httpx2.AsyncClient, project_id: str, **overrides: Any
) -> dict[str, Any]:
    response = await client.post(f"/projects/{project_id}/test-cases", json=GET_ORDERS | overrides)
    assert response.status_code == 201, response.text  # noqa: S101
    case: dict[str, Any] = response.json()
    return case
