"""Pins down every difference planted between the two demo APIs.

ParityLens is supposed to find these on its own. This file is the answer
key: if a demo API changes and a difference disappears, the demo silently
stops demonstrating anything, so each one is asserted here against both
apps directly. The numbers match the table in demo/README.md.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from legacy_shop_api.main import create_app as create_legacy_app
from modern_shop_api.main import create_app as create_modern_app

SINGLE_LINE_ORDER = {"customer_name": "John", "items": [{"sku": "A-100", "quantity": 3}]}
# 198 and 105 each lose a fraction of a yen when taxed separately.
TWO_LINE_ORDER = {
    "customer_name": "John",
    "items": [{"sku": "B-200", "quantity": 1}, {"sku": "A-100", "quantity": 1}],
}
MIGRATED_ORDER_ID = "ORD-000001"


@pytest.fixture
def legacy() -> Iterator[TestClient]:
    with TestClient(create_legacy_app()) as client:
        yield client


@pytest.fixture
def modern() -> Iterator[TestClient]:
    with TestClient(create_modern_app()) as client:
        yield client


def create_order(client: TestClient, payload: dict[str, Any]) -> dict[str, Any]:
    response = client.post("/orders", json=payload)
    assert response.status_code == 201
    body: dict[str, Any] = response.json()
    return body


def test_single_line_orders_agree_on_amounts(legacy: TestClient, modern: TestClient) -> None:
    """The baseline: where nothing is planted, the two APIs really do agree."""
    old = create_order(legacy, SINGLE_LINE_ORDER)
    new = create_order(modern, SINGLE_LINE_ORDER)

    for field in ("customer_name", "subtotal", "tax", "total", "status"):
        assert old[field] == new[field]
    assert (old["subtotal"], old["tax"], old["total"]) == (315, 31, 346)


def test_01_ids_and_timestamps_change_on_every_call(legacy: TestClient, modern: TestClient) -> None:
    old_first = create_order(legacy, SINGLE_LINE_ORDER)
    old_second = create_order(legacy, SINGLE_LINE_ORDER)
    new = create_order(modern, SINGLE_LINE_ORDER)

    assert old_first["id"] != old_second["id"]
    assert old_first["id"].startswith("ORD-")
    assert not new["id"].startswith("ORD-")
    assert old_first["created_at"].endswith("+09:00")
    assert new["created_at"].endswith("Z")


def test_02_modern_adds_currency(legacy: TestClient, modern: TestClient) -> None:
    assert "currency" not in create_order(legacy, SINGLE_LINE_ORDER)
    assert create_order(modern, SINGLE_LINE_ORDER)["currency"] == "JPY"


def test_03_missing_customer_name_is_no_longer_rejected(
    legacy: TestClient, modern: TestClient
) -> None:
    payload = {"items": [{"sku": "A-100", "quantity": 1}]}

    assert legacy.post("/orders", json=payload).status_code == 400
    assert modern.post("/orders", json=payload).status_code == 201


def test_04_tax_differs_by_one_yen_on_multi_line_orders(
    legacy: TestClient, modern: TestClient
) -> None:
    old = create_order(legacy, TWO_LINE_ORDER)
    new = create_order(modern, TWO_LINE_ORDER)

    assert old["subtotal"] == new["subtotal"] == 303
    assert (old["tax"], old["total"]) == (29, 332)
    assert (new["tax"], new["total"]) == (30, 333)


def test_05_cancel_answers_200_with_body_versus_204(legacy: TestClient, modern: TestClient) -> None:
    old_id = create_order(legacy, SINGLE_LINE_ORDER)["id"]
    new_id = create_order(modern, SINGLE_LINE_ORDER)["id"]

    old = legacy.delete(f"/orders/{old_id}")
    new = modern.delete(f"/orders/{new_id}")

    assert old.status_code == 200
    assert old.json() == {"id": old_id, "status": "cancelled"}
    assert new.status_code == 204
    assert new.content == b""
    # Both sides agree on the effect, only the response differs.
    assert legacy.get(f"/orders/{old_id}").json()["status"] == "cancelled"
    assert modern.get(f"/orders/{new_id}").json()["status"] == "cancelled"


def test_06_quantity_is_a_string_in_legacy_and_a_number_in_modern(
    legacy: TestClient, modern: TestClient
) -> None:
    assert create_order(legacy, SINGLE_LINE_ORDER)["items"][0]["quantity"] == "3"
    assert create_order(modern, SINGLE_LINE_ORDER)["items"][0]["quantity"] == 3


def test_07_item_order_differs(legacy: TestClient, modern: TestClient) -> None:
    old = create_order(legacy, TWO_LINE_ORDER)
    new = create_order(modern, TWO_LINE_ORDER)

    assert [item["sku"] for item in old["items"]] == ["A-100", "B-200"]
    assert [item["sku"] for item in new["items"]] == ["B-200", "A-100"]


def test_08_migrated_order_timestamp_is_nine_hours_off(
    legacy: TestClient, modern: TestClient
) -> None:
    old = legacy.get(f"/orders/{MIGRATED_ORDER_ID}").json()
    new = modern.get(f"/orders/{MIGRATED_ORDER_ID}").json()

    assert old["created_at"] == "2026-01-15T10:00:00+09:00"
    assert new["created_at"] == "2026-01-15T10:00:00Z"
    # Unlike difference 1, this value is the same every time it is read.
    assert legacy.get(f"/orders/{MIGRATED_ORDER_ID}").json()["created_at"] == old["created_at"]


def test_09_not_found_bodies_have_different_shapes(legacy: TestClient, modern: TestClient) -> None:
    old = legacy.get("/orders/does-not-exist")
    new = modern.get("/orders/does-not-exist")

    assert old.status_code == new.status_code == 404
    assert set(old.json()) == {"error"}
    assert set(new.json()) == {"detail"}


def test_10_invalid_quantity_answers_400_versus_422(legacy: TestClient, modern: TestClient) -> None:
    payload = {"customer_name": "John", "items": [{"sku": "A-100", "quantity": 0}]}

    assert legacy.post("/orders", json=payload).status_code == 400
    assert modern.post("/orders", json=payload).status_code == 422
