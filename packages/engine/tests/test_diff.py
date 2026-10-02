"""The deterministic diff, before severity: what differs and where."""

from typing import Any

import pytest
from paritylens_engine import DiffKind, RuleSet, UnorderedRule
from paritylens_engine.diff import RawDifference, diff_json
from paritylens_engine.jsonvalue import parse_json
from paritylens_engine.rules import compile_rules

NO_RULES = compile_rules(RuleSet())


def diff(old: Any, new: Any, rules: RuleSet | None = None) -> list[RawDifference]:
    compiled = compile_rules(rules) if rules else NO_RULES
    return diff_json(old, new, compiled)


def summary(differences: list[RawDifference]) -> list[tuple[DiffKind, str]]:
    return [(d.kind, d.location) for d in differences]


@pytest.mark.parametrize(
    "document",
    [None, True, 0, "text", [], {}, {"a": [1, {"b": None}], "c": "x"}],
)
def test_identical_documents_have_no_differences(document: Any) -> None:
    assert diff(document, document) == []


# --- scalars -----------------------------------------------------------------


def test_value_changed() -> None:
    [difference] = diff({"price": 100}, {"price": 101})

    assert difference.kind is DiffKind.VALUE_CHANGED
    assert difference.location == "$.price"
    assert (difference.old, difference.new) == (100, 101)


@pytest.mark.parametrize(
    ("old", "new", "detail"),
    [
        (100, "100", "number → string"),
        ("3", 3, "string → number"),
        (1, True, "number → boolean"),
        (0, False, "number → boolean"),
        (None, "", "null → string"),
        ("", None, "string → null"),
        ({}, [], "object → array"),
        ([1], {"0": 1}, "array → object"),
    ],
)
def test_type_changed(old: Any, new: Any, detail: str) -> None:
    [difference] = diff({"field": old}, {"field": new})

    assert difference.kind is DiffKind.TYPE_CHANGED
    assert difference.location == "$.field"
    assert difference.detail == detail


def test_a_type_change_is_reported_once_not_per_nested_field() -> None:
    differences = diff({"address": {"city": "Tokyo", "zip": "100"}}, {"address": "Tokyo 100"})

    assert summary(differences) == [(DiffKind.TYPE_CHANGED, "$.address")]


@pytest.mark.parametrize(
    ("old", "new"),
    [("100", "100.0"), ("100", "1e2"), ("0.10", "0.1"), ("-0", "0")],
)
def test_numbers_equal_in_value_are_equal_whatever_their_spelling(old: str, new: str) -> None:
    assert diff(parse_json(old), parse_json(new)) == []


def test_numbers_that_only_a_float_would_confuse_are_different() -> None:
    differences = diff(parse_json("1.0000000000000001"), parse_json("1.0"))

    assert summary(differences) == [(DiffKind.VALUE_CHANGED, "$")]


def test_strings_are_compared_exactly() -> None:
    assert summary(diff("John", "john")) == [(DiffKind.VALUE_CHANGED, "$")]
    assert summary(diff("a", "a ")) == [(DiffKind.VALUE_CHANGED, "$")]


# --- objects -----------------------------------------------------------------


def test_field_added() -> None:
    [difference] = diff({"a": 1}, {"a": 1, "currency": "JPY"})

    assert (difference.kind, difference.location) == (DiffKind.FIELD_ADDED, "$.currency")
    assert difference.new == "JPY"


def test_field_removed() -> None:
    [difference] = diff({"a": 1, "legacy_code": "X"}, {"a": 1})

    assert (difference.kind, difference.location) == (DiffKind.FIELD_REMOVED, "$.legacy_code")
    assert difference.old == "X"


def test_null_is_a_value_and_absent_is_not() -> None:
    """A client that reads response.note crashes on a missing field, not on null."""
    assert summary(diff({"note": None}, {})) == [(DiffKind.FIELD_REMOVED, "$.note")]
    assert summary(diff({}, {"note": None})) == [(DiffKind.FIELD_ADDED, "$.note")]
    assert diff({"note": None}, {"note": None}) == []


def test_field_order_does_not_matter() -> None:
    assert diff({"a": 1, "b": 2}, {"b": 2, "a": 1}) == []


def test_a_rename_is_a_removal_and_an_addition() -> None:
    differences = diff({"error": "not found"}, {"detail": "not found"})

    assert summary(differences) == [
        (DiffKind.FIELD_REMOVED, "$.error"),
        (DiffKind.FIELD_ADDED, "$.detail"),
    ]


def test_differences_are_reported_in_document_order() -> None:
    old = {"z": 1, "a": {"y": 1, "b": 1}, "m": 1}
    new = {"z": 2, "a": {"y": 2, "b": 2}, "m": 2, "extra": 0}

    assert [d.location for d in diff(old, new)] == ["$.z", "$.a.y", "$.a.b", "$.m", "$.extra"]


def test_nested_paths() -> None:
    differences = diff({"a": {"b": [{"c": 1}]}}, {"a": {"b": [{"c": 2}]}})

    assert summary(differences) == [(DiffKind.VALUE_CHANGED, "$.a.b[0].c")]


# --- ordered arrays (the default) ----------------------------------------------


def test_arrays_are_compared_position_by_position() -> None:
    differences = diff({"tags": ["a", "b"]}, {"tags": ["b", "a"]})

    assert summary(differences) == [
        (DiffKind.VALUE_CHANGED, "$.tags[0]"),
        (DiffKind.VALUE_CHANGED, "$.tags[1]"),
    ]


def test_a_longer_array_reports_the_extra_elements() -> None:
    [difference] = diff([1, 2], [1, 2, 3, 4])

    assert (difference.kind, difference.location) == (DiffKind.ARRAY_CHANGED, "$")
    assert (difference.old, difference.new) == ([], [3, 4])
    assert difference.detail == "length 2 → 4"


def test_a_shorter_array_reports_the_missing_elements() -> None:
    [difference] = diff([1, 2, 3], [1])

    assert (difference.old, difference.new) == ([2, 3], [])
    assert difference.detail == "length 3 → 1"


def test_shared_positions_are_still_compared_when_lengths_differ() -> None:
    differences = diff([{"id": 1}, {"id": 2}], [{"id": 9}])

    assert summary(differences) == [
        (DiffKind.VALUE_CHANGED, "$[0].id"),
        (DiffKind.ARRAY_CHANGED, "$"),
    ]


# --- unordered arrays, without a key -------------------------------------------

UNORDERED_TAGS = RuleSet(unordered=(UnorderedRule(path="$.tags"),))


def test_unordered_arrays_ignore_order() -> None:
    assert diff({"tags": ["a", "b", "c"]}, {"tags": ["c", "a", "b"]}, UNORDERED_TAGS) == []


def test_unordered_arrays_still_count_duplicates() -> None:
    [difference] = diff({"tags": ["a", "a", "b"]}, {"tags": ["a", "b", "b"]}, UNORDERED_TAGS)

    assert difference.kind is DiffKind.ARRAY_CHANGED
    assert (difference.old, difference.new) == (["a"], ["b"])
    assert difference.detail == "1 element(s) only in old, 1 only in new"


def test_unordered_matching_does_not_confuse_true_with_one() -> None:
    [difference] = diff({"tags": [1]}, {"tags": [True]}, UNORDERED_TAGS)

    assert difference.kind is DiffKind.ARRAY_CHANGED


def test_unordered_matching_treats_equal_numbers_as_equal() -> None:
    old, new = parse_json('{"tags": [1.0, 2]}'), parse_json('{"tags": [2.00, 1]}')

    assert diff(old, new, UNORDERED_TAGS) == []


def test_the_unordered_rule_applies_only_to_the_array_it_names() -> None:
    rules = RuleSet(unordered=(UnorderedRule(path="$.a"),))

    assert diff({"a": [1, 2], "b": [1, 2]}, {"a": [2, 1], "b": [2, 1]}, rules) != []
    assert summary(diff({"a": [1, 2], "b": [1, 2]}, {"a": [2, 1], "b": [1, 2]}, rules)) == []


def test_unordered_matching_looks_past_ignored_fields() -> None:
    rules = RuleSet(unordered=(UnorderedRule(path="$.rows"),), ignore=("$.rows[*].id",))
    old = {"rows": [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]}
    new = {"rows": [{"id": 8, "name": "b"}, {"id": 9, "name": "a"}]}

    assert diff(old, new, rules) == []


# --- unordered arrays, with a key ----------------------------------------------

BY_SKU = RuleSet(unordered=(UnorderedRule(path="$.items", key="sku"),))


def test_keyed_arrays_pair_elements_by_key_and_compare_inside() -> None:
    old = {"items": [{"sku": "A", "qty": 1}, {"sku": "B", "qty": 2}]}
    new = {"items": [{"sku": "B", "qty": 2}, {"sku": "A", "qty": 5}]}

    [difference] = diff(old, new, BY_SKU)

    assert difference.kind is DiffKind.VALUE_CHANGED
    assert difference.location == "$.items[sku=A].qty"
    assert (difference.old, difference.new) == (1, 5)


def test_keyed_arrays_report_elements_without_a_partner() -> None:
    old = {"items": [{"sku": "A"}, {"sku": "B"}]}
    new = {"items": [{"sku": "B"}, {"sku": "C"}]}

    [difference] = diff(old, new, BY_SKU)

    assert (difference.kind, difference.location) == (DiffKind.ARRAY_CHANGED, "$.items")
    assert (difference.old, difference.new) == ([{"sku": "A"}], [{"sku": "C"}])


@pytest.mark.parametrize(
    "unusable",
    [
        [{"sku": "A"}, {"sku": "A"}],  # repeated key
        [{"sku": "A"}, {"name": "no key"}],  # missing key
        [{"sku": "A"}, "not an object"],
        [{"sku": {"nested": 1}}],
        [{"sku": None}],
    ],
)
def test_a_key_that_cannot_identify_elements_falls_back_to_whole_element_matching(
    unusable: list[Any],
) -> None:
    assert diff({"items": unusable}, {"items": list(reversed(unusable))}, BY_SKU) == []


def test_unordered_rules_can_use_wildcards() -> None:
    rules = RuleSet(unordered=(UnorderedRule(path="$.orders[*].items", key="sku"),))
    old = {"orders": [{"items": [{"sku": "A"}, {"sku": "B"}]}]}
    new = {"orders": [{"items": [{"sku": "B"}, {"sku": "A"}]}]}

    assert diff(old, new, rules) == []


# --- found in review ----------------------------------------------------------


@pytest.mark.parametrize(("old", "new"), [("1.50", "1.5"), ("1", "1.0"), ("1e2", "100")])
def test_keyed_pairing_treats_equal_numbers_as_the_same_key(old: str, new: str) -> None:
    rules = RuleSet(unordered=(UnorderedRule(path="$.items", key="id"),))
    old_doc = parse_json(f'{{"items": [{{"id": {old}, "q": 1}}]}}')
    new_doc = parse_json(f'{{"items": [{{"id": {new}, "q": 1}}]}}')

    assert diff(old_doc, new_doc, rules) == []


def test_whole_element_matching_honours_nested_unordered_rules() -> None:
    rules = RuleSet(
        unordered=(UnorderedRule(path="$.items"), UnorderedRule(path="$.items[*].tags"))
    )
    old = {"items": [{"id": 1, "tags": ["a", "b"]}, {"id": 2, "tags": []}]}
    new = {"items": [{"id": 2, "tags": []}, {"id": 1, "tags": ["b", "a"]}]}

    assert diff(old, new, rules) == []


def test_whole_element_matching_honours_ignore_rules_on_nested_positions() -> None:
    rules = RuleSet(unordered=(UnorderedRule(path="$.items"),), ignore=("$.items[*].a[1]",))

    assert diff({"items": [{"a": [1, 2]}]}, {"items": [{"a": [1, 3]}]}, rules) == []


def test_elements_of_an_unordered_array_have_no_position() -> None:
    """[0] cannot mean anything where order does not; only [*] applies."""
    by_index = RuleSet(unordered=(UnorderedRule(path="$.items"),), ignore=("$.items[0].ts",))
    by_any = RuleSet(unordered=(UnorderedRule(path="$.items"),), ignore=("$.items[*].ts",))
    old = {"items": [{"a": 1, "ts": 1}, {"a": 2, "ts": 2}]}
    new = {"items": [{"a": 2, "ts": 9}, {"a": 1, "ts": 1}]}

    [difference] = diff(old, new, by_index)
    assert (difference.old, difference.new) == ([{"a": 2, "ts": 2}], [{"a": 2, "ts": 9}])
    assert diff(old, new, by_any) == []


def test_an_ignored_unordered_array_still_lists_what_differs_inside() -> None:
    rules = RuleSet(unordered=(UnorderedRule(path="$.items"),), ignore=("$.items",))

    assert summary(diff({"items": [{"a": 1}]}, {"items": [{"a": 2}]}, rules)) == [
        (DiffKind.VALUE_CHANGED, "$.items[0].a")
    ]
