from decimal import Decimal

import pytest
from paritylens_engine.jsonvalue import (
    MAX_VALUE_CHARS,
    InvalidJsonError,
    clip,
    json_type,
    parse_json,
    to_plain,
)


def test_fractional_numbers_are_parsed_exactly() -> None:
    assert parse_json("0.1") == Decimal("0.1")
    # As floats these two would be the same number.
    assert parse_json("1.0000000000000001") != parse_json("1.0")


def test_integers_stay_integers_at_any_size() -> None:
    value = parse_json("123456789012345678901234567890")

    assert value == 123456789012345678901234567890
    assert isinstance(value, int)


@pytest.mark.parametrize("text", ["", "{", "NaN", "Infinity", "-Infinity", "{'a': 1}", "undefined"])
def test_invalid_json_is_rejected(text: str) -> None:
    with pytest.raises(InvalidJsonError):
        parse_json(text)


def test_deeply_nested_json_is_rejected_instead_of_crashing() -> None:
    with pytest.raises(InvalidJsonError):
        parse_json("[" * 100_000 + "]" * 100_000)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "null"),
        (True, "boolean"),
        (False, "boolean"),
        (0, "number"),
        (1, "number"),
        (Decimal("1.5"), "number"),
        ("", "string"),
        ([], "array"),
        ({}, "object"),
    ],
)
def test_json_type(value: object, expected: str) -> None:
    assert json_type(value) == expected  # type: ignore[arg-type]


def test_to_plain_keeps_a_number_when_nothing_is_lost() -> None:
    assert to_plain(Decimal("0.5")) == 0.5
    assert to_plain({"a": [Decimal("1.25")]}) == {"a": [1.25]}


def test_to_plain_falls_back_to_exact_digits() -> None:
    assert to_plain(Decimal("1.0000000000000001")) == "1.0000000000000001"


def test_clip_leaves_small_values_alone() -> None:
    assert clip({"a": [1, "x", None]}) == {"a": [1, "x", None]}


def test_clip_shortens_long_strings() -> None:
    clipped = clip("x" * (MAX_VALUE_CHARS + 50))

    assert isinstance(clipped, str)
    assert len(clipped) == MAX_VALUE_CHARS + 1
    assert clipped.endswith("…")


def test_clip_summarises_large_containers() -> None:
    assert clip(list(range(5000))) == "<array of 5000 items>"
    assert clip({str(i): i for i in range(5000)}) == "<object with 5000 fields>"


# --- inputs that used to crash or be misread ---------------------------------


def test_an_exponent_beyond_what_decimal_accepts_is_rejected_cleanly() -> None:
    with pytest.raises(InvalidJsonError):
        parse_json("[1e99999999999999999999]")


def test_integers_longer_than_pythons_digit_limit_are_still_numbers() -> None:
    value = parse_json("1" * 5000)

    assert json_type(value) == "number"
    assert value == parse_json("1" * 5000)
    assert value != parse_json("1" * 4999 + "2")


def test_nesting_beyond_the_limit_is_rejected() -> None:
    from paritylens_engine.jsonvalue import MAX_DEPTH

    assert parse_json("[" * MAX_DEPTH + "]" * MAX_DEPTH) is not None
    with pytest.raises(InvalidJsonError):
        parse_json("[" * (MAX_DEPTH + 2) + "]" * (MAX_DEPTH + 2))


def test_lone_surrogates_are_made_printable() -> None:
    """JSON may contain "\\ud800" alone; UTF-8 cannot encode it."""
    value = parse_json('{"\\ud800": "a\\ud800b"}')

    assert value == {"\\ud800": "a\\ud800b"}
    assert parse_json('"\\ud83d\\ude00"') == "\U0001f600"  # a proper pair is left alone


def test_clip_makes_text_printable() -> None:
    assert clip("x\ud800") == "x\\ud800"
