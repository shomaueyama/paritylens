import pytest
from paritylens_engine import RuleSet, UnorderedRule
from pydantic import ValidationError


def test_an_empty_ruleset_is_valid() -> None:
    assert RuleSet() == RuleSet(ignore=(), unordered=(), critical=(), compare_headers=())


@pytest.mark.parametrize(
    "fields",
    [
        {"ignore": ("$[oops",)},
        {"critical": ("",)},
        {"unordered": (UnorderedRule(path="$."),)},
    ],
)
def test_a_malformed_pattern_is_rejected_when_the_ruleset_is_built(
    fields: dict[str, object],
) -> None:
    """Fail when the rule is saved, not in the middle of a run."""
    with pytest.raises(ValidationError):
        RuleSet(**fields)  # type: ignore[arg-type]


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        RuleSet(ignored=("$.a",))  # type: ignore[call-arg]


def test_header_names_are_lowercased() -> None:
    assert RuleSet(compare_headers=("ETag", "Cache-Control")).compare_headers == (
        "etag",
        "cache-control",
    )


def test_rulesets_round_trip_through_json() -> None:
    rules = RuleSet(
        ignore=("$..request_id",),
        unordered=(UnorderedRule(path="$.items", key="sku"),),
        critical=("$..total",),
        compare_headers=("etag",),
        critical_field_names=False,
    )

    assert RuleSet.model_validate_json(rules.model_dump_json()) == rules


def test_an_empty_key_is_rejected() -> None:
    with pytest.raises(ValidationError):
        UnorderedRule(path="$.items", key="")


def test_the_clock_tolerance_has_an_upper_bound() -> None:
    with pytest.raises(ValidationError):
        RuleSet(clock_tolerance_seconds=10**14)


def test_the_number_of_rules_is_bounded() -> None:
    with pytest.raises(ValidationError):
        RuleSet(ignore=tuple(f"$.f{n}" for n in range(201)))
