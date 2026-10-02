"""Severity: how serious each kind of difference is, and why."""

from typing import Any

import pytest
from paritylens_engine import (
    Difference,
    DiffKind,
    Hint,
    NoiseSource,
    Reason,
    ResponseSnapshot,
    RuleSet,
    Severity,
    UnorderedRule,
    compare_step,
)
from paritylens_engine.severity import sounds_like_money
from paritylens_engine.testing import json_response


def only_difference(old: Any, new: Any, rules: RuleSet | None = None) -> Difference:
    [difference] = compare_step(json_response(old), json_response(new), rules=rules).differences
    return difference


def test_severities_are_ordered() -> None:
    ranks = [severity.rank for severity in Severity]

    assert ranks == sorted(ranks)
    assert Severity.NONE.rank < Severity.LOW.rank < Severity.CRITICAL.rank


@pytest.mark.parametrize(
    ("old", "new", "kind", "severity"),
    [
        ({"a": 1}, {"a": 1, "extra": True}, DiffKind.FIELD_ADDED, Severity.LOW),
        ({"name": "John"}, {"name": "Jon"}, DiffKind.VALUE_CHANGED, Severity.MEDIUM),
        ({"tags": ["a"]}, {"tags": ["a", "b"]}, DiffKind.ARRAY_CHANGED, Severity.MEDIUM),
        ({"a": 1, "gone": 2}, {"a": 1}, DiffKind.FIELD_REMOVED, Severity.HIGH),
        ({"quantity": "3"}, {"quantity": 3}, DiffKind.TYPE_CHANGED, Severity.HIGH),
    ],
)
def test_default_severity_per_kind(old: Any, new: Any, kind: DiffKind, severity: Severity) -> None:
    difference = only_difference(old, new)

    assert (difference.kind, difference.severity) == (kind, severity)
    assert difference.reason is Reason.DEFAULT_FOR_KIND
    assert difference.noise_source is None


def test_body_format_change_is_high() -> None:
    comparison = compare_step(json_response({"a": 1}), ResponseSnapshot(status=200, body="plain"))

    assert [(d.kind, d.severity) for d in comparison.differences] == [
        (DiffKind.BODY_FORMAT_CHANGED, Severity.HIGH)
    ]


def test_header_change_is_low() -> None:
    comparison = compare_step(
        ResponseSnapshot(status=200, headers={"etag": "1"}),
        ResponseSnapshot(status=200, headers={"etag": "2"}),
        rules=RuleSet(compare_headers=("etag",)),
    )

    assert [(d.kind, d.severity) for d in comparison.differences] == [
        (DiffKind.HEADER_CHANGED, Severity.LOW)
    ]


# --- status ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("old", "new"),
    [(200, 201), (200, 204), (400, 422), (404, 410), (500, 503), (400, 500), (200, 302)],
)
def test_a_status_change_that_keeps_the_outcome_is_high(old: int, new: int) -> None:
    [difference] = compare_step(
        ResponseSnapshot(status=old), ResponseSnapshot(status=new)
    ).differences

    assert difference.kind is DiffKind.STATUS_CHANGED
    assert (difference.severity, difference.reason) == (Severity.HIGH, Reason.DEFAULT_FOR_KIND)


@pytest.mark.parametrize(
    ("old", "new"), [(400, 200), (400, 201), (200, 500), (204, 404), (302, 403)]
)
def test_a_status_change_that_flips_success_and_failure_is_critical(old: int, new: int) -> None:
    [difference] = compare_step(
        ResponseSnapshot(status=old), ResponseSnapshot(status=new)
    ).differences

    assert (difference.severity, difference.reason) == (Severity.CRITICAL, Reason.OUTCOME_FLIPPED)


# --- critical fields -----------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "total",
        "tax",
        "balance",
        "price",
        "unit_price",
        "line_total",
        "tax_amount",
        "taxAmount",
        "unitPrice",
        "TOTAL",
        "shipping-fee",
        "subtotal",
        "Discount",
    ],
)
def test_names_that_sound_like_money(name: str) -> None:
    assert sounds_like_money(name)


@pytest.mark.parametrize(
    "name",
    [
        "total_count",
        "totalPages",
        "price_label",
        "name",
        "id",
        "created_at",
        "taxonomy",
        "subtotals_by_region",
        "feedback",
        "",
        "123",
    ],
)
def test_names_that_do_not(name: str) -> None:
    assert not sounds_like_money(name)


def test_a_changed_amount_is_critical() -> None:
    difference = only_difference({"balance": 10000}, {"balance": 9999})

    assert (difference.severity, difference.reason) == (
        Severity.CRITICAL,
        Reason.CRITICAL_FIELD_NAME,
    )


def test_an_amount_inside_an_array_is_critical() -> None:
    difference = only_difference({"items": [{"line_total": 315}]}, {"items": [{"line_total": 316}]})

    assert difference.path == "$.items[0].line_total"
    assert difference.severity is Severity.CRITICAL


@pytest.mark.parametrize(
    ("old", "new", "kind"),
    [
        ({"total": 100}, {"total": "100"}, DiffKind.TYPE_CHANGED),
        ({"total": 100}, {}, DiffKind.FIELD_REMOVED),
    ],
)
def test_a_retyped_or_missing_amount_is_critical(old: Any, new: Any, kind: DiffKind) -> None:
    difference = only_difference(old, new)

    assert (difference.kind, difference.severity) == (kind, Severity.CRITICAL)


def test_a_new_amount_field_is_not_critical() -> None:
    """Nothing a client already reads has changed."""
    difference = only_difference({"a": 1}, {"a": 1, "tax": 10})

    assert (difference.kind, difference.severity) == (DiffKind.FIELD_ADDED, Severity.LOW)


def test_the_name_heuristic_can_be_turned_off() -> None:
    difference = only_difference({"total": 1}, {"total": 2}, RuleSet(critical_field_names=False))

    assert difference.severity is Severity.MEDIUM


def test_a_critical_rule_marks_a_field_the_heuristic_would_miss() -> None:
    difference = only_difference({"kingaku": 1}, {"kingaku": 2}, RuleSet(critical=("$.kingaku",)))

    assert (difference.severity, difference.reason) == (Severity.CRITICAL, Reason.CRITICAL_RULE)


def test_a_critical_rule_covers_what_is_inside_it() -> None:
    difference = only_difference(
        {"settlement": {"lines": [{"value": 1}]}},
        {"settlement": {"lines": [{"value": 2}]}},
        RuleSet(critical=("$.settlement",)),
    )

    assert difference.severity is Severity.CRITICAL


# --- ignore rules --------------------------------------------------------------


def test_an_ignored_difference_is_kept_but_carries_no_severity() -> None:
    difference = only_difference(
        {"request_id": "a"}, {"request_id": "b"}, RuleSet(ignore=("request_id",))
    )

    assert difference.kind is DiffKind.VALUE_CHANGED
    assert (difference.severity, difference.reason, difference.noise_source) == (
        Severity.NONE,
        Reason.IGNORE_RULE,
        NoiseSource.RULE,
    )


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ({"meta": {"a": 1}}, {"meta": {"a": "1"}}),  # type changed inside
        ({"meta": {"a": 1}}, {}),  # removed entirely
        ({"meta": {"total": 1}}, {"meta": {"total": 2}}),  # even an amount
    ],
)
def test_ignore_wins_over_every_other_rule(old: Any, new: Any) -> None:
    difference = only_difference(old, new, RuleSet(ignore=("$.meta",), critical=("$.meta",)))

    assert difference.severity is Severity.NONE


# --- hints ---------------------------------------------------------------------


def test_values_shaped_like_uuids_get_a_hint_but_keep_their_severity() -> None:
    difference = only_difference(
        {"id": "53e59e2f-26e5-4e78-a913-6c6cb26f3527"},
        {"id": "0b9c5b1e-7f43-4f0a-9d53-2f6a3f1f0c11"},
    )

    assert difference.severity is Severity.MEDIUM
    assert difference.hints == (Hint.LOOKS_LIKE_UUID,)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("2026-01-15T10:00:00+09:00", "2026-01-15T10:00:00Z"),
        ("2026-01-15T10:00:00.123456Z", "2026-01-15 10:00"),
    ],
)
def test_values_shaped_like_timestamps_get_a_hint(old: str, new: str) -> None:
    difference = only_difference({"at": old}, {"at": new})

    assert difference.hints == (Hint.LOOKS_LIKE_TIMESTAMP,)


def test_no_hint_when_only_one_side_matches_the_shape() -> None:
    difference = only_difference(
        {"id": "ORD-000002"}, {"id": "53e59e2f-26e5-4e78-a913-6c6cb26f3527"}
    )

    assert difference.hints == ()


def test_large_values_are_summarised_in_the_difference() -> None:
    difference = only_difference({"rows": list(range(5000))}, {})

    assert difference.old == "<array of 5000 items>"


# --- found in review ----------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["prices", "fees", "taxes", "totals", "total_jpy", "amount_usd", "priceInCents"]
)
def test_plurals_and_unit_suffixes_still_sound_like_money(name: str) -> None:
    assert sounds_like_money(name)


@pytest.mark.parametrize("name", ["feed", "news_feed", "taxi", "jpy", "in_cents", "address"])
def test_lookalikes_do_not(name: str) -> None:
    assert not sounds_like_money(name)


def test_an_unordered_array_cannot_hide_a_changed_amount() -> None:
    """Whole-element matching reports the array, not the field, but the
    severity must not drop because of how the difference was found."""
    rules = RuleSet(unordered=(UnorderedRule(path="$.items"),))

    difference = only_difference(
        {"items": [{"sku": "A", "price": 100}]}, {"items": [{"sku": "A", "price": 1}]}, rules
    )

    assert difference.kind is DiffKind.ARRAY_CHANGED
    assert (difference.severity, difference.reason) == (
        Severity.CRITICAL,
        Reason.CRITICAL_FIELD_NAME,
    )


def test_an_unmatched_element_under_a_critical_rule_is_critical() -> None:
    rules = RuleSet(unordered=(UnorderedRule(path="$.rows"),), critical=("$.rows[*].p",))

    difference = only_difference({"rows": [{"p": 1}]}, {"rows": [{"p": 2}]}, rules)

    assert (difference.severity, difference.reason) == (Severity.CRITICAL, Reason.CRITICAL_RULE)


def test_elements_only_added_to_an_array_are_not_critical() -> None:
    difference = only_difference({"items": []}, {"items": [{"price": 100}]})

    assert (difference.kind, difference.severity) == (DiffKind.ARRAY_CHANGED, Severity.MEDIUM)


def test_removing_an_array_element_that_holds_an_amount_is_critical() -> None:
    difference = only_difference({"items": [{"price": 100}]}, {"items": []})

    assert (difference.kind, difference.severity) == (DiffKind.ARRAY_CHANGED, Severity.CRITICAL)


@pytest.mark.parametrize("new", [{}, {"order": "see /orders/1"}])
def test_removing_or_retyping_the_parent_of_an_amount_is_critical(new: Any) -> None:
    difference = only_difference({"order": {"lines": [{"line_total": 1}]}}, new)

    assert difference.path == "$.order"
    assert difference.severity is Severity.CRITICAL


def test_removing_a_parent_without_amounts_is_high() -> None:
    difference = only_difference({"links": {"self": "/a", "next": "/b"}}, {})

    assert difference.severity is Severity.HIGH
