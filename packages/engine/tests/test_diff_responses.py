"""Comparing whole responses: status, headers, body format, and when to stop."""

from paritylens_engine import DiffKind, Note, ResponseSnapshot, RuleSet
from paritylens_engine.diff import diff_responses
from paritylens_engine.rules import compile_rules
from paritylens_engine.testing import json_response, text_response

NO_RULES = compile_rules(RuleSet())


def kinds_and_locations(old: ResponseSnapshot, new: ResponseSnapshot) -> list[tuple[DiffKind, str]]:
    differences, _ = diff_responses(old, new, NO_RULES)
    return [(d.kind, d.location) for d in differences]


def test_identical_responses() -> None:
    assert diff_responses(json_response({"a": 1}), json_response({"a": 1}), NO_RULES) == ([], [])


def test_status_changed_within_the_same_class_still_compares_bodies() -> None:
    old, new = json_response({"a": 1}, status=200), json_response({"a": 2}, status=201)

    assert kinds_and_locations(old, new) == [
        (DiffKind.STATUS_CHANGED, "status"),
        (DiffKind.VALUE_CHANGED, "$.a"),
    ]


def test_bodies_are_not_compared_across_status_classes() -> None:
    old = json_response({"error": {"code": "VALIDATION_ERROR"}}, status=400)
    new = json_response({"id": "abc", "total": 100}, status=201)

    differences, notes = diff_responses(old, new, NO_RULES)

    assert [(d.kind, d.old, d.new) for d in differences] == [(DiffKind.STATUS_CHANGED, 400, 201)]
    assert notes == [Note.BODY_NOT_COMPARED_STATUS_CLASS]


def test_truncated_bodies_are_not_compared() -> None:
    old = ResponseSnapshot(status=200, body='{"a": 1', body_truncated=True)
    new = json_response({"a": 2})

    differences, notes = diff_responses(old, new, NO_RULES)

    assert differences == []
    assert notes == [Note.BODY_NOT_COMPARED_TRUNCATED]


def test_json_body_versus_no_body() -> None:
    old = json_response({"id": "1", "status": "cancelled"}, status=200)
    new = ResponseSnapshot(status=204)

    differences, _ = diff_responses(old, new, NO_RULES)

    assert [(d.kind, d.location, d.old, d.new) for d in differences] == [
        (DiffKind.STATUS_CHANGED, "status", 200, 204),
        (DiffKind.BODY_FORMAT_CHANGED, "body", "json", "empty"),
    ]


def test_two_empty_bodies_are_equal() -> None:
    assert kinds_and_locations(ResponseSnapshot(status=204), ResponseSnapshot(status=204)) == []
    assert kinds_and_locations(text_response(None), text_response("")) == []


def test_json_versus_text() -> None:
    old, new = json_response({"ok": True}), text_response("OK")

    differences, _ = diff_responses(old, new, NO_RULES)

    assert [(d.kind, d.old, d.new) for d in differences] == [
        (DiffKind.BODY_FORMAT_CHANGED, "json", "text")
    ]


def test_text_bodies_are_compared_exactly() -> None:
    differences, _ = diff_responses(text_response("hello"), text_response("hello!"), NO_RULES)

    assert [(d.kind, d.location) for d in differences] == [(DiffKind.VALUE_CHANGED, "body")]


def test_a_different_json_media_type_is_reported_and_the_bodies_still_compared() -> None:
    old = json_response({"a": 1})
    new = ResponseSnapshot(
        status=200, headers={"Content-Type": "application/problem+json"}, body='{"a": 2}'
    )

    differences, _ = diff_responses(old, new, NO_RULES)

    assert [(d.kind, d.location, d.old, d.new) for d in differences] == [
        (DiffKind.BODY_FORMAT_CHANGED, "body", "application/json", "application/problem+json"),
        (DiffKind.VALUE_CHANGED, "$.a", 1, 2),
    ]


def test_content_type_parameters_and_case_do_not_matter() -> None:
    old = ResponseSnapshot(status=200, headers={"Content-Type": "application/json"}, body="{}")
    new = ResponseSnapshot(
        status=200, headers={"content-type": "Application/JSON; charset=UTF-8"}, body="{}"
    )

    assert kinds_and_locations(old, new) == []


def test_json_served_as_text_is_still_compared_as_json() -> None:
    old = text_response('{"a": 1, "b": 2}', content_type="text/plain")
    new = text_response('{"b": 2, "a": 1}', content_type="text/plain")

    assert kinds_and_locations(old, new) == []


def test_invalid_json_with_a_json_content_type_is_compared_as_text() -> None:
    old = text_response("{broken", content_type="application/json")
    new = text_response("{broken", content_type="application/json")

    assert kinds_and_locations(old, new) == []
    assert kinds_and_locations(old, json_response({})) == [(DiffKind.BODY_FORMAT_CHANGED, "body")]


def test_headers_are_compared_only_when_asked_for() -> None:
    old = ResponseSnapshot(status=200, headers={"Cache-Control": "no-store", "X-Trace": "1"})
    new = ResponseSnapshot(status=200, headers={"cache-control": "max-age=60", "X-Trace": "2"})
    rules = compile_rules(RuleSet(compare_headers=("Cache-Control",)))

    differences, _ = diff_responses(old, new, rules)

    assert [(d.kind, d.location, d.old, d.new) for d in differences] == [
        (DiffKind.HEADER_CHANGED, "header.cache-control", "no-store", "max-age=60")
    ]
    assert kinds_and_locations(old, new) == []


def test_a_header_present_on_one_side_only() -> None:
    old = ResponseSnapshot(status=200, headers={"etag": '"abc"'})
    new = ResponseSnapshot(status=200)
    rules = compile_rules(RuleSet(compare_headers=("etag",)))

    differences, _ = diff_responses(old, new, rules)

    assert [(d.old, d.new) for d in differences] == [('"abc"', None)]


# --- found in review ----------------------------------------------------------


def test_a_byte_order_mark_is_not_content() -> None:
    old = text_response('\ufeff{"a": 1}', content_type="application/json")

    assert kinds_and_locations(old, json_response({"a": 1})) == []
    assert kinds_and_locations(old, json_response({"a": 2})) == [(DiffKind.VALUE_CHANGED, "$.a")]


def test_a_whitespace_only_body_is_empty() -> None:
    assert kinds_and_locations(text_response("  \n"), text_response(None)) == []


def test_content_type_does_not_matter_when_there_is_no_body() -> None:
    old = ResponseSnapshot(status=204, headers={"content-type": "application/json"})
    new = ResponseSnapshot(status=204)

    assert kinds_and_locations(old, new) == []
