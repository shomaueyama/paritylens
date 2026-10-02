from decimal import Decimal
from typing import Any

import pytest
from paritylens_engine.template import (
    MissingVariableError,
    placeholders,
    render_text,
    render_value,
)


def test_placeholders_are_replaced() -> None:
    assert render_text("/orders/{{order_id}}", {"order_id": "ORD-1"}) == "/orders/ORD-1"
    assert render_text("{{a}}-{{ b }}-{{a}}", {"a": "x", "b": "y"}) == "x-y-x"


def test_text_without_placeholders_is_unchanged() -> None:
    assert render_text("/orders?limit=10", {}) == "/orders?limit=10"
    assert render_text("{ not a placeholder }", {}) == "{ not a placeholder }"


@pytest.mark.parametrize(
    ("value", "text"),
    [("abc", "abc"), (42, "42"), (Decimal("1.5"), "1.5"), (True, "true"), (None, "null")],
)
def test_values_inside_text_are_written_as_text(value: Any, text: str) -> None:
    assert render_text("v={{v}}", {"v": value}) == f"v={text}"


def test_a_missing_variable_is_an_error_that_names_it() -> None:
    with pytest.raises(MissingVariableError) as raised:
        render_text("/orders/{{order_id}}", {"other": 1})

    assert raised.value.name == "order_id"


def test_a_string_that_is_only_a_placeholder_keeps_the_variables_type() -> None:
    variables: dict[str, Any] = {"id": 123, "price": Decimal("9.5"), "flag": True, "tags": ["a"]}

    assert render_value({"order_id": "{{id}}"}, variables) == {"order_id": 123}
    assert render_value(["{{price}}", "{{flag}}", "{{tags}}"], variables) == [9.5, True, ["a"]]


def test_a_placeholder_inside_longer_text_becomes_text() -> None:
    assert render_value({"ref": "order-{{id}}"}, {"id": 123}) == {"ref": "order-123"}


def test_render_value_leaves_other_values_alone() -> None:
    document: Any = {"a": 1, "b": [True, None, "plain"], "c": {"d": 1.5}}

    assert render_value(document, {}) == document


def test_placeholders_lists_every_variable_used() -> None:
    document: Any = {"a": "{{x}}", "b": ["{{y}}-{{z}}", 1], "{{k}}": None}

    assert placeholders(document) == {"x", "y", "z", "k"}
    assert placeholders("plain") == set()
    assert placeholders(None) == set()


def test_objects_and_arrays_inside_text_are_written_as_json() -> None:
    assert render_text("v={{v}}", {"v": {"a": True, "b": None}}) == 'v={"a": true, "b": null}'
    assert render_text("v={{v}}", {"v": [1, "x"]}) == 'v=[1, "x"]'
