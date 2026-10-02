import pytest
from paritylens_engine.paths import (
    KeyMatch,
    Path,
    PathSyntaxError,
    generalize,
    last_field_name,
    parse_pattern,
    render,
)


@pytest.mark.parametrize(
    ("path", "text"),
    [
        ((), "$"),
        (("a",), "$.a"),
        (("a", "b"), "$.a.b"),
        (("items", 0, "price"), "$.items[0].price"),
        (("items", KeyMatch("sku", "A-100"), "quantity"), "$.items[sku=A-100].quantity"),
        (("first name",), "$['first name']"),
        (("it's",), "$['it\\'s']"),
        (("a.b",), "$['a.b']"),
        (("金額",), "$.金額"),
    ],
)
def test_render(path: Path, text: str) -> None:
    assert render(path) == text


@pytest.mark.parametrize(
    "path",
    [
        (),
        ("a", "b"),
        ("items", 3, "price"),
        ("items", KeyMatch("sku", "A-100"), "quantity"),
        ("first name", "it's", "a.b", "back\\slash"),
    ],
)
def test_a_rendered_path_parses_back_to_a_pattern_matching_only_that_path(path: Path) -> None:
    """What the screen shows can be pasted into a rule and mean the same place."""
    pattern = parse_pattern(render(path))

    assert pattern.matches(path)
    assert not pattern.matches((*path, "extra"))


@pytest.mark.parametrize(
    ("pattern", "path", "expected"),
    [
        ("$", (), True),
        ("$", ("a",), False),
        ("$.a", ("a",), True),
        ("$.a", ("b",), False),
        ("$.a", ("a", "b"), False),
        ("$.items[0]", ("items", 0), True),
        ("$.items[0]", ("items", 1), False),
        ("$.items[*]", ("items", 7), True),
        ("$.items[*]", ("items", KeyMatch("sku", "A-100")), True),
        ("$.items[*]", ("items", "name"), False),
        ("$.items[*].id", ("items", 2, "id"), True),
        ("$.a.*", ("a", "anything"), True),
        ("$.a.*", ("a", 0), False),
        ("$..id", ("id",), True),
        ("$..id", ("items", 0, "id"), True),
        ("$..id", ("items", 0, "identifier"), False),
        ("$..meta.id", ("a", "meta", "id"), True),
        ("$..meta.id", ("a", "meta", "x", "id"), False),
        ("$.a..id", ("a", "b", "c", "id"), True),
        ("$.a..id", ("b", "id"), False),
        ("created_at", ("order", "created_at"), True),
        ("created_at", ("created_at",), True),
        ("$.items[sku=A-100]", ("items", KeyMatch("sku", "A-100")), True),
        ("$.items[sku=A-100]", ("items", KeyMatch("sku", "B-200")), False),
        ("$['first name']", ("first name",), True),
        # A numeric field name is a field, not an index.
        ("$..0", ("a", 0), False),
    ],
)
def test_matches(pattern: str, path: Path, expected: bool) -> None:
    assert parse_pattern(pattern).matches(path) is expected


def test_covers_includes_everything_inside_the_matched_place() -> None:
    pattern = parse_pattern("$.meta")

    assert pattern.covers(("meta",))
    assert pattern.covers(("meta", "trace", "id"))
    assert not pattern.covers(("metadata",))
    assert not pattern.covers(())


def test_covers_the_root_covers_everything() -> None:
    assert parse_pattern("$").covers(("anything", 0, "at all"))


@pytest.mark.parametrize(
    "pattern",
    ["", "   ", "$.", "$..", "$[", "$[abc]", "$[=x]", "$x", "a b", "$.a b", "$.a[1.5]", "$.a[-1]"],
)
def test_malformed_patterns_are_rejected(pattern: str) -> None:
    with pytest.raises(PathSyntaxError):
        parse_pattern(pattern)


def test_generalize_replaces_array_positions() -> None:
    assert generalize(("items", 0, "id")) == "$.items[*].id"
    assert generalize(("items", KeyMatch("sku", "A-100"), "id")) == "$.items[*].id"
    assert generalize(("a", "b")) == "$.a.b"
    assert generalize(()) == "$"


def test_generalized_paths_are_valid_patterns() -> None:
    assert parse_pattern(generalize(("items", 4, "first name"))).matches(("items", 9, "first name"))


def test_last_field_name_skips_array_positions() -> None:
    assert last_field_name(("items", 0, "price")) == "price"
    assert last_field_name(("totals", 2)) == "totals"
    assert last_field_name((0, 1)) is None
    assert last_field_name(()) is None


@pytest.mark.parametrize(
    "segment",
    [
        KeyMatch("sku", "A]1"),
        KeyMatch("a=b", "1"),
        KeyMatch("sku", "A][sku=B"),
        KeyMatch("sku", ""),
        KeyMatch("sku", "it's"),
        KeyMatch("first name", "x y"),
        KeyMatch("sku", "back\\slash"),
    ],
)
def test_keyed_segments_with_special_characters_round_trip(segment: KeyMatch) -> None:
    path: Path = ("items", segment, "price")
    pattern = parse_pattern(render(path))

    assert pattern.matches(path)
    assert not pattern.matches(("items", KeyMatch(segment.key, segment.value + "x"), "price"))


def test_plain_keyed_segments_keep_the_short_form() -> None:
    assert render(("items", KeyMatch("sku", "A-100"))) == "$.items[sku=A-100]"
    assert render(("items", KeyMatch("sku", "A 1"))) == "$.items['sku'='A 1']"


def test_many_descendant_segments_do_not_take_exponential_time() -> None:
    """Without memoisation this pattern took over a minute on this path."""
    pattern = parse_pattern("$" + "..a" * 8 + "..zzz")
    path: Path = ("a",) * 60

    assert not pattern.matches(path)
    assert not pattern.covers(path)
