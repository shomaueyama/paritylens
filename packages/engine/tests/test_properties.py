"""Properties that must hold for any JSON document, checked on generated ones.

The example-based tests say what the engine does in the cases someone
thought of. These say what must stay true in the cases nobody did.
"""

import json
from typing import Any

from hypothesis import given
from hypothesis import strategies as st
from paritylens_engine import (
    DiffKind,
    ResponseSnapshot,
    RuleSet,
    Severity,
    UnorderedRule,
    compare_step,
)
from paritylens_engine.diff import diff_json
from paritylens_engine.jsonvalue import parse_json
from paritylens_engine.paths import parse_pattern
from paritylens_engine.rules import compile_rules

NO_RULES = compile_rules(RuleSet())

scalars = (
    st.none()
    | st.booleans()
    | st.integers(min_value=-(10**12), max_value=10**12)
    | st.floats(allow_nan=False, allow_infinity=False, width=32)
    | st.text(max_size=8)
)
documents = st.recursive(
    scalars,
    lambda children: (
        st.lists(children, max_size=4) | st.dictionaries(st.text(max_size=6), children, max_size=4)
    ),
    max_leaves=25,
)


def response(document: Any) -> ResponseSnapshot:
    return ResponseSnapshot(
        status=200, headers={"content-type": "application/json"}, body=json.dumps(document)
    )


def parsed(document: Any) -> Any:
    """The document as the engine reads it off the wire."""
    return parse_json(json.dumps(document))


@given(documents)
def test_a_document_never_differs_from_itself(document: Any) -> None:
    assert diff_json(parsed(document), parsed(document), NO_RULES) == []


@given(documents, documents)
def test_swapping_the_sides_swaps_added_and_removed(a: Any, b: Any) -> None:
    mirror = {
        DiffKind.FIELD_ADDED: DiffKind.FIELD_REMOVED,
        DiffKind.FIELD_REMOVED: DiffKind.FIELD_ADDED,
    }

    forward = sorted((d.kind, d.location) for d in diff_json(parsed(a), parsed(b), NO_RULES))
    backward = sorted(
        (mirror.get(d.kind, d.kind), d.location) for d in diff_json(parsed(b), parsed(a), NO_RULES)
    )

    assert forward == backward


@given(documents, documents)
def test_the_comparison_is_deterministic(a: Any, b: Any) -> None:
    assert compare_step(response(a), response(b)) == compare_step(response(a), response(b))


@given(documents, documents)
def test_every_reported_path_is_a_valid_pattern_for_that_place(a: Any, b: Any) -> None:
    """Any path shown to a user can be turned into a rule as is."""
    for difference in diff_json(parsed(a), parsed(b), NO_RULES):
        assert difference.path is not None
        assert parse_pattern(difference.location).matches(difference.path)


@given(documents, documents)
def test_ignoring_the_whole_body_leaves_nothing_to_report(a: Any, b: Any) -> None:
    comparison = compare_step(response(a), response(b), rules=RuleSet(ignore=("$",)))

    assert comparison.max_severity is Severity.NONE


@given(documents, documents)
def test_ignoring_one_difference_silences_it_and_changes_nothing_else(a: Any, b: Any) -> None:
    before = compare_step(response(a), response(b)).differences
    for target in before:
        after = compare_step(response(a), response(b), rules=RuleSet(ignore=(target.path,)))

        assert len(after.differences) == len(before)
        for was, now in zip(before, after.differences, strict=True):
            assert (now.kind, now.path) == (was.kind, was.path)
            assert now.severity.rank <= was.severity.rank
            if now.path == target.path:
                assert now.severity is Severity.NONE


@given(documents, documents)
def test_a_baseline_identical_to_the_old_response_changes_nothing(a: Any, b: Any) -> None:
    """If the old API answered the same twice, nothing can be called volatile."""
    assert compare_step(response(a), response(b), baseline=response(a)) == compare_step(
        response(a), response(b)
    )


@given(documents, documents)
def test_a_baseline_never_makes_a_difference_more_severe(a: Any, baseline: Any) -> None:
    # Build "new" from "old" by reusing old where possible keeps this cheap:
    # any pair of documents exercises the property.
    without = compare_step(response(a), response(baseline))
    with_baseline = compare_step(response(a), response(baseline), baseline=response(baseline))

    for plain, judged in zip(without.differences, with_baseline.differences, strict=True):
        assert judged.severity.rank <= plain.severity.rank


@given(st.lists(documents, max_size=6), st.randoms(use_true_random=False))
def test_an_unordered_array_equals_any_reordering_of_itself(items: list[Any], rng: Any) -> None:
    shuffled = list(items)
    rng.shuffle(shuffled)
    rules = compile_rules(RuleSet(unordered=(UnorderedRule(path="$.items"),)))

    assert diff_json(parsed({"items": items}), parsed({"items": shuffled}), rules) == []


# --- the engine never raises, and its results can always be written out --------

keyed_rules = RuleSet(
    unordered=(UnorderedRule(path="$.items", key="id"), UnorderedRule(path="$..tags")),
    ignore=("$..ts",),
)
keys = st.sampled_from(["id", "ts", "tags", "items", "total", "a"]) | st.text(max_size=4)
keyed_documents = st.recursive(
    scalars,
    lambda children: st.lists(children, max_size=4) | st.dictionaries(keys, children, max_size=5),
    max_leaves=25,
)


@given(keyed_documents, keyed_documents, keyed_documents)
def test_comparing_never_fails_and_the_result_serialises(a: Any, b: Any, c: Any) -> None:
    comparison = compare_step(response(a), response(b), baseline=response(c), rules=keyed_rules)

    restored = type(comparison).model_validate_json(comparison.model_dump_json())
    assert restored == comparison
    for difference in comparison.differences:
        if difference.path.startswith("$"):
            parse_pattern(difference.path)


@given(st.text(max_size=200), st.text(max_size=200), st.sampled_from([None, "application/json"]))
def test_arbitrary_text_bodies_never_fail(old: str, new: str, content_type: str | None) -> None:
    headers = {"content-type": content_type} if content_type else {}
    comparison = compare_step(
        ResponseSnapshot(status=200, headers=headers, body=old),
        ResponseSnapshot(status=200, headers=headers, body=new),
    )

    comparison.model_dump_json()


@given(keyed_documents)
def test_rules_do_not_make_a_document_differ_from_itself(document: Any) -> None:
    comparison = compare_step(response(document), response(document), rules=keyed_rules)

    assert comparison.differences == ()
