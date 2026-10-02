"""Baseline noise detection: what the old API changes on its own is not a difference."""

from paritylens_engine import (
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
)
from paritylens_engine.testing import json_response


def by_path(comparison: StepComparison) -> dict[str, tuple[DiffKind, Severity]]:
    return {d.path: (d.kind, d.severity) for d in comparison.differences}


def test_a_value_that_changes_between_two_old_calls_is_noise() -> None:
    old = json_response({"id": "ORD-2", "name": "John"})
    again = json_response({"id": "ORD-3", "name": "John"})
    new = json_response({"id": "f3b1", "name": "John"})

    [difference] = compare_step(old, new, baseline=again).differences

    assert difference.path == "$.id"
    assert (difference.severity, difference.reason, difference.noise_source) == (
        Severity.NONE,
        Reason.VOLATILE_IN_BASELINE,
        NoiseSource.BASELINE,
    )


def test_a_value_that_is_stable_in_the_old_api_is_a_real_difference() -> None:
    """The same field can be noise in one response and a finding in another."""
    old = json_response({"created_at": "2026-01-15T10:00:00+09:00"})
    again = json_response({"created_at": "2026-01-15T10:00:00+09:00"})
    new = json_response({"created_at": "2026-01-15T10:00:00Z"})

    [difference] = compare_step(old, new, baseline=again).differences

    assert difference.severity is Severity.MEDIUM
    assert difference.noise_source is None
    assert difference.hints == (Hint.LOOKS_LIKE_TIMESTAMP,)


def test_without_a_baseline_nothing_is_assumed_to_be_noise() -> None:
    old, new = json_response({"id": "ORD-2"}), json_response({"id": "f3b1"})

    [difference] = compare_step(old, new).differences

    assert difference.severity is Severity.MEDIUM


def test_volatility_carries_across_array_positions() -> None:
    old = json_response({"rows": [{"id": 1, "v": "a"}, {"id": 2, "v": "b"}]})
    again = json_response({"rows": [{"id": 7, "v": "a"}, {"id": 2, "v": "b"}]})
    new = json_response({"rows": [{"id": 1, "v": "a"}, {"id": 99, "v": "b"}]})

    comparison = compare_step(old, new, baseline=again)

    # Only rows[0].id varied in the baseline, but rows[1].id is the same field.
    assert by_path(comparison) == {"$.rows[1].id": (DiffKind.VALUE_CHANGED, Severity.NONE)}


def test_a_type_change_on_a_volatile_field_is_still_reported() -> None:
    """The ID changes every call, but it was always a string. Now it is a number."""
    old = json_response({"id": "ORD-2"})
    again = json_response({"id": "ORD-3"})
    new = json_response({"id": 12345})

    [difference] = compare_step(old, new, baseline=again).differences

    assert (difference.kind, difference.severity) == (DiffKind.TYPE_CHANGED, Severity.HIGH)
    assert difference.noise_source is None


def test_a_removed_volatile_field_is_still_reported() -> None:
    old = json_response({"id": "ORD-2", "a": 1})
    again = json_response({"id": "ORD-3", "a": 1})
    new = json_response({"a": 1})

    [difference] = compare_step(old, new, baseline=again).differences

    assert (difference.kind, difference.severity) == (DiffKind.FIELD_REMOVED, Severity.HIGH)


def test_a_volatile_amount_is_noise_too() -> None:
    """If the old API's own total moves between calls, it cannot be compared."""
    old, again = json_response({"total": 100}), json_response({"total": 105})
    new = json_response({"total": 90})

    [difference] = compare_step(old, new, baseline=again).differences

    assert difference.severity is Severity.NONE


def test_structural_differences_seen_in_the_baseline_are_kept_but_flagged() -> None:
    old = json_response({"rows": [1, 2]})
    again = json_response({"rows": [1, 2, 3]})
    new = json_response({"rows": [1]})

    [difference] = compare_step(old, new, baseline=again).differences

    assert (difference.kind, difference.severity) == (DiffKind.ARRAY_CHANGED, Severity.MEDIUM)
    assert difference.hints == (Hint.BASELINE_ALSO_DIFFERS,)


def test_a_baseline_that_disagrees_on_status_is_flagged_as_unstable() -> None:
    old, again = json_response({}, status=200), json_response({}, status=503)
    new = json_response({}, status=200)

    comparison = compare_step(old, new, baseline=again)

    assert comparison.differences == ()
    assert comparison.notes == (Note.BASELINE_UNSTABLE,)


def test_ignore_rules_take_precedence_over_the_baseline() -> None:
    old, again = json_response({"id": "a"}), json_response({"id": "b"})
    new = json_response({"id": "c"})

    [difference] = compare_step(old, new, baseline=again, rules=RuleSet(ignore=("id",))).differences

    assert difference.noise_source is NoiseSource.RULE


def test_volatility_inside_keyed_arrays() -> None:
    rules = RuleSet(unordered=(UnorderedRule(path="$.items", key="sku"),))
    old = json_response({"items": [{"sku": "A", "token": "1"}, {"sku": "B", "token": "2"}]})
    again = json_response({"items": [{"sku": "A", "token": "3"}, {"sku": "B", "token": "4"}]})
    new = json_response({"items": [{"sku": "B", "token": "5"}, {"sku": "A", "token": "6"}]})

    comparison = compare_step(old, new, baseline=again, rules=rules)

    assert {d.severity for d in comparison.differences} == {Severity.NONE}
    assert [d.path for d in comparison.differences] == [
        "$.items[sku=A].token",
        "$.items[sku=B].token",
    ]


def test_text_bodies_that_vary_in_the_baseline_are_noise() -> None:
    old = ResponseSnapshot(status=200, body="generated at 10:00")
    again = ResponseSnapshot(status=200, body="generated at 10:01")
    new = ResponseSnapshot(status=200, body="generated at 10:02")

    [difference] = compare_step(old, new, baseline=again).differences

    assert (difference.path, difference.severity) == ("body", Severity.NONE)


def test_max_severity_of_a_comparison() -> None:
    comparison = compare_step(
        json_response({"a": 1, "name": "x", "gone": 1}),
        json_response({"a": 1, "name": "y", "added": 1}),
    )

    assert comparison.max_severity is Severity.HIGH
    assert StepComparison().max_severity is Severity.NONE


# --- found in review ----------------------------------------------------------


def test_a_critical_rule_outranks_the_baseline() -> None:
    """What the user wrote beats what the engine inferred."""
    old, again, new = json_response({"x": 1}), json_response({"x": 2}), json_response({"x": 3})

    [difference] = compare_step(
        old, new, baseline=again, rules=RuleSet(critical=("$.x",))
    ).differences

    assert (difference.severity, difference.reason) == (Severity.CRITICAL, Reason.CRITICAL_RULE)
