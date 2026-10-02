"""The engine against the demo APIs: does it find what was planted?

test_planted_differences.py proves the differences exist. This proves the
engine finds each one and gives it the severity demo/README.md promises,
without being told where to look: the only rule in use says that order
items are matched by SKU.
"""

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient
from legacy_shop_api.main import create_app as create_legacy_app
from modern_shop_api.main import create_app as create_modern_app
from paritylens_engine import (
    Difference,
    DiffKind,
    Hint,
    NoiseSource,
    Note,
    Reason,
    ResponseSnapshot,
    RuleSet,
    Severity,
    StepComparison,
    UnorderedRule,
    compare_step,
    verdict_for,
)
from paritylens_engine.model import Verdict

RULES = RuleSet(unordered=(UnorderedRule(path="$.items", key="sku"),))

SINGLE_LINE_ORDER = {"customer_name": "John", "items": [{"sku": "A-100", "quantity": 3}]}
TWO_LINE_ORDER = {
    "customer_name": "John",
    "items": [{"sku": "B-200", "quantity": 1}, {"sku": "A-100", "quantity": 1}],
}

type Call = Callable[[TestClient], httpx2.Response]


@pytest.fixture
def legacy() -> Iterator[TestClient]:
    with TestClient(create_legacy_app()) as client:
        yield client


@pytest.fixture
def modern() -> Iterator[TestClient]:
    with TestClient(create_modern_app()) as client:
        yield client


def snapshot(response: httpx2.Response) -> ResponseSnapshot:
    return ResponseSnapshot(
        status=response.status_code,
        headers=dict(response.headers),
        body=response.text or None,
        received_at=datetime.now(UTC),
    )


def run(
    call: Call, legacy: TestClient, modern: TestClient, rules: RuleSet = RULES
) -> StepComparison:
    """Send the same request to the old API twice and the new API once, then compare."""
    old, old_again, new = call(legacy), call(legacy), call(modern)
    return compare_step(snapshot(old), snapshot(new), baseline=snapshot(old_again), rules=rules)


def post_order(payload: dict[str, Any]) -> Call:
    return lambda client: client.post("/orders", json=payload)


def find(comparison: StepComparison, path: str) -> Difference:
    [difference] = [d for d in comparison.differences if d.path == path]
    return difference


def test_01_ids_and_timestamps_are_recognised_as_noise(
    legacy: TestClient, modern: TestClient
) -> None:
    comparison = run(post_order(SINGLE_LINE_ORDER), legacy, modern)

    order_id, created_at = find(comparison, "$.id"), find(comparison, "$.created_at")
    assert (order_id.severity, order_id.noise_source) == (Severity.NONE, NoiseSource.BASELINE)
    assert created_at.severity is Severity.NONE
    # The legacy timestamp has one-second resolution, so two calls usually
    # return the same value and the baseline cannot see it move. Which test
    # catches it depends on whether a second ticked over in between.
    assert created_at.noise_source in (NoiseSource.CLOCK, NoiseSource.BASELINE)


def test_02_the_new_currency_field_is_low(legacy: TestClient, modern: TestClient) -> None:
    difference = find(run(post_order(SINGLE_LINE_ORDER), legacy, modern), "$.currency")

    assert (difference.kind, difference.severity) == (DiffKind.FIELD_ADDED, Severity.LOW)


def test_03_the_relaxed_validation_is_critical(legacy: TestClient, modern: TestClient) -> None:
    comparison = run(post_order({"items": [{"sku": "A-100", "quantity": 1}]}), legacy, modern)

    [difference] = comparison.differences
    assert (difference.kind, difference.old, difference.new) == (DiffKind.STATUS_CHANGED, 400, 201)
    assert (difference.severity, difference.reason) == (Severity.CRITICAL, Reason.OUTCOME_FLIPPED)
    assert comparison.notes == (Note.BODY_NOT_COMPARED_STATUS_CLASS,)


def test_04_the_one_yen_tax_difference_is_critical(legacy: TestClient, modern: TestClient) -> None:
    comparison = run(post_order(TWO_LINE_ORDER), legacy, modern)

    tax, total = find(comparison, "$.tax"), find(comparison, "$.total")
    assert (tax.old, tax.new, tax.severity) == (29, 30, Severity.CRITICAL)
    assert (total.old, total.new, total.severity) == (332, 333, Severity.CRITICAL)
    assert tax.reason is Reason.CRITICAL_FIELD_NAME


def test_04_single_line_orders_show_no_amount_difference(
    legacy: TestClient, modern: TestClient
) -> None:
    """The bug needs two lines to appear, which is why it survives simple tests."""
    comparison = run(post_order(SINGLE_LINE_ORDER), legacy, modern)

    assert not [d for d in comparison.differences if d.path in ("$.tax", "$.total", "$.subtotal")]


def test_05_the_cancel_response_change_is_high(legacy: TestClient, modern: TestClient) -> None:
    def create_then_cancel(client: TestClient) -> httpx2.Response:
        order_id = client.post("/orders", json=SINGLE_LINE_ORDER).json()["id"]
        return client.delete(f"/orders/{order_id}")

    comparison = run(create_then_cancel, legacy, modern)

    assert [(d.kind, d.path, d.severity) for d in comparison.differences] == [
        (DiffKind.STATUS_CHANGED, "status", Severity.HIGH),
        (DiffKind.BODY_FORMAT_CHANGED, "body", Severity.HIGH),
    ]


def test_06_the_quantity_type_change_is_high(legacy: TestClient, modern: TestClient) -> None:
    difference = find(
        run(post_order(SINGLE_LINE_ORDER), legacy, modern), "$.items[sku=A-100].quantity"
    )

    assert (difference.kind, difference.old, difference.new) == (DiffKind.TYPE_CHANGED, "3", 3)
    assert difference.severity is Severity.HIGH


def test_07_item_order_is_a_difference_until_a_rule_says_otherwise(
    legacy: TestClient, modern: TestClient
) -> None:
    without_rule = run(post_order(TWO_LINE_ORDER), legacy, modern, rules=RuleSet())
    with_rule = run(post_order(TWO_LINE_ORDER), legacy, modern)

    assert any(d.path == "$.items[0].sku" for d in without_rule.differences)
    # With the rule, the only differences left inside items are the quantity types.
    assert {d.path for d in with_rule.differences if d.path.startswith("$.items")} == {
        "$.items[sku=A-100].quantity",
        "$.items[sku=B-200].quantity",
    }


def test_08_the_migrated_timestamp_is_a_real_difference(
    legacy: TestClient, modern: TestClient
) -> None:
    """Same field as in 01, but here the old API returns the same value every time."""
    comparison = run(lambda client: client.get("/orders/ORD-000001"), legacy, modern)

    difference = find(comparison, "$.created_at")
    assert (difference.kind, difference.severity) == (DiffKind.VALUE_CHANGED, Severity.MEDIUM)
    assert difference.noise_source is None
    assert difference.hints == (Hint.LOOKS_LIKE_TIMESTAMP,)
    # The ID is stable here too, and equal on both sides.
    assert not [d for d in comparison.differences if d.path == "$.id"]


def test_09_the_error_body_shape_change_is_high(legacy: TestClient, modern: TestClient) -> None:
    comparison = run(lambda client: client.get("/orders/does-not-exist"), legacy, modern)

    assert [(d.kind, d.path, d.severity) for d in comparison.differences] == [
        (DiffKind.FIELD_REMOVED, "$.error", Severity.HIGH),
        (DiffKind.FIELD_ADDED, "$.detail", Severity.LOW),
    ]


def test_10_the_validation_status_change_is_high(legacy: TestClient, modern: TestClient) -> None:
    payload = {"customer_name": "John", "items": [{"sku": "A-100", "quantity": 0}]}

    comparison = run(post_order(payload), legacy, modern)

    status = find(comparison, "status")
    assert (status.old, status.new, status.severity) == (400, 422, Severity.HIGH)


def test_every_demo_scenario_is_breaking_except_none(
    legacy: TestClient, modern: TestClient
) -> None:
    """A plain order already breaks compatibility, through the quantity type alone."""
    comparison = run(post_order(SINGLE_LINE_ORDER), legacy, modern)

    assert verdict_for(comparison.max_severity) is Verdict.BREAKING
