from typing import Any

import pytest
from paritylens_engine.suite import Suite
from pydantic import ValidationError


def suite_with(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "targets": {
            "old": {"base_url": "http://old.test"},
            "new": {"base_url": "http://new.test"},
        },
        "cases": [{"name": "get", "steps": [{"request": {"method": "GET", "path": "/orders"}}]}],
    }
    document.update(overrides)
    return document


def case_with_steps(*steps: dict[str, Any]) -> dict[str, Any]:
    return suite_with(cases=[{"name": "case", "steps": list(steps)}])


def error_of(document: dict[str, Any]) -> str:
    with pytest.raises(ValidationError) as raised:
        Suite.model_validate(document)
    return str(raised.value)


def test_a_minimal_suite_loads() -> None:
    suite = Suite.model_validate(suite_with())

    assert suite.targets.old.base_url == "http://old.test"
    assert suite.cases[0].noise_detection is True
    assert suite.cases[0].step_id(0) == "step-1"


def test_the_method_is_case_insensitive() -> None:
    suite = Suite.model_validate(
        case_with_steps({"request": {"method": "post", "path": "/orders", "json": {"a": 1}}})
    )

    assert suite.cases[0].steps[0].request.method == "POST"
    assert suite.cases[0].steps[0].request.json_body == {"a": 1}


def test_a_trailing_slash_on_the_base_url_is_dropped() -> None:
    suite = Suite.model_validate(
        suite_with(
            targets={
                "old": {"base_url": "http://old.test/api/"},
                "new": {"base_url": "http://new.test"},
            }
        )
    )

    assert suite.targets.old.base_url == "http://old.test/api"


@pytest.mark.parametrize(
    "base_url",
    ["old.test", "ftp://old.test", "file:///etc/passwd", "http://", "http://a.test/?q=1", ""],
)
def test_a_base_url_must_be_plain_http(base_url: str) -> None:
    document = suite_with(
        targets={"old": {"base_url": base_url}, "new": {"base_url": "http://new.test"}}
    )

    assert "base_url" in error_of(document)


def test_a_path_must_be_relative() -> None:
    document = case_with_steps({"request": {"method": "GET", "path": "http://evil.test/x"}})

    assert "path must start with '/'" in error_of(document)


def test_json_and_body_are_mutually_exclusive() -> None:
    document = case_with_steps(
        {"request": {"method": "POST", "path": "/a", "json": {"a": 1}, "body": "raw"}}
    )

    assert "either 'json' or 'body'" in error_of(document)


def test_unknown_fields_are_rejected() -> None:
    document = case_with_steps({"request": {"method": "GET", "path": "/a"}, "captures": {}})

    assert "captures" in error_of(document)


def test_a_variable_used_before_it_is_captured_fails_at_load_time() -> None:
    document = case_with_steps({"request": {"method": "GET", "path": "/orders/{{order_id}}"}})

    assert "order_id used before a step captures it" in error_of(document)


def test_a_variable_captured_by_an_earlier_step_can_be_used_anywhere_in_a_request() -> None:
    document = case_with_steps(
        {"request": {"method": "POST", "path": "/orders"}, "capture": {"order_id": "$.id"}},
        {
            "request": {
                "method": "PUT",
                "path": "/orders/{{order_id}}",
                "query": {"ref": "{{order_id}}"},
                "headers": {"x-order": "{{order_id}}"},
                "json": {"parent": "{{order_id}}"},
            }
        },
    )

    assert len(Suite.model_validate(document).cases[0].steps) == 2


@pytest.mark.parametrize("path", ["$.items[*].id", "$..id", "id", "$.a.*", "$[oops"])
def test_a_capture_path_must_name_one_place(path: str) -> None:
    document = case_with_steps(
        {"request": {"method": "GET", "path": "/a"}, "capture": {"value": path}}
    )

    Suite.model_validate(
        case_with_steps({"request": {"method": "GET", "path": "/a"}, "capture": {"v": "$.a[0].b"}})
    )
    error_of(document)


def test_variable_names_must_be_identifiers() -> None:
    document = case_with_steps(
        {"request": {"method": "GET", "path": "/a"}, "capture": {"order-id": "$.id"}}
    )

    error_of(document)


def test_step_ids_must_be_unique_within_a_case() -> None:
    step = {"id": "same", "request": {"method": "GET", "path": "/a"}}

    assert "step ids must be unique" in error_of(case_with_steps(step, step))


def test_a_case_needs_at_least_one_step_and_a_suite_at_least_one_case() -> None:
    error_of(suite_with(cases=[]))
    error_of(suite_with(cases=[{"name": "empty", "steps": []}]))


def test_too_many_steps_are_rejected() -> None:
    step = {"request": {"method": "GET", "path": "/a"}}

    error_of(case_with_steps(*[step] * 21))


def test_invalid_rules_are_rejected_with_the_suite() -> None:
    error_of(suite_with(rules={"ignore": ["$[oops"]}))


# --- found in review ----------------------------------------------------------------


def targets(old: str) -> dict[str, Any]:
    return suite_with(targets={"old": {"base_url": old}, "new": {"base_url": "http://new.test"}})


@pytest.mark.parametrize(
    "base_url",
    [
        "http://admin:hunter2@old.test",
        "http://admin@old.test",
        "http://old.test?",
        "http://old.test#",
        "http://old\t.test",
        "http://old.test:abc",
        "http://old .test",
    ],
)
def test_base_urls_that_would_misbehave_at_run_time_are_rejected_at_load_time(
    base_url: str,
) -> None:
    error_of(targets(base_url))


def test_a_rejected_base_url_is_not_repeated_in_the_error() -> None:
    """It may be rejected precisely because it holds a password."""
    assert "hunter2" not in error_of(targets("http://admin:hunter2@old.test"))


@pytest.mark.parametrize("path", ["/orders?status=open", "/orders#top", "/x\ny", "/a b", "/a\tb"])
def test_paths_with_queries_fragments_or_whitespace_are_rejected(path: str) -> None:
    message = error_of(case_with_steps({"request": {"method": "GET", "path": path}}))

    assert "put query parameters under 'query'" in message


@pytest.mark.parametrize(
    "headers",
    [
        {"X-Note": "日本語"},
        {"X-Nöte": "a"},
        {"X Note": "a"},
        {"X-Note": "line\nbreak"},
        {"Host": "internal.example"},
        {"content-length": "0"},
        {"Transfer-Encoding": "chunked"},
    ],
)
def test_headers_that_cannot_be_sent_as_written_are_rejected(headers: dict[str, str]) -> None:
    error_of(case_with_steps({"request": {"method": "GET", "path": "/", "headers": headers}}))
    error_of(suite_with(headers=headers))


def test_placeholders_are_not_allowed_in_suite_or_target_headers() -> None:
    """They are sent before any step has run, so they could never be filled in."""
    message = error_of(suite_with(headers={"Authorization": "Bearer {{token}}"}))

    assert "placeholders can only be used in a step's headers" in message
    error_of(
        suite_with(
            targets={
                "old": {"base_url": "http://old.test", "headers": {"X-A": "{{a}}"}},
                "new": {"base_url": "http://new.test"},
            }
        )
    )


def test_an_explicit_step_id_may_not_collide_with_an_automatic_one() -> None:
    document = case_with_steps(
        {"id": "step-2", "request": {"method": "GET", "path": "/a"}},
        {"request": {"method": "GET", "path": "/b"}},
    )

    assert "step ids must be unique" in error_of(document)


def test_a_capture_can_be_a_path_or_a_path_with_options() -> None:
    suite = Suite.model_validate(
        case_with_steps(
            {
                "request": {"method": "POST", "path": "/login"},
                "capture": {
                    "plain": "$.id",
                    "token": {"path": "$.access_token", "secret": True},
                    "keyed": "$.items[sku=A-100].id",
                },
            }
        )
    )

    capture = suite.cases[0].steps[0].capture
    assert (capture["plain"].path, capture["plain"].secret) == ("$.id", False)
    assert (capture["token"].path, capture["token"].secret) == ("$.access_token", True)


def test_too_many_captures_in_one_step_are_rejected() -> None:
    capture = {f"v{n}": "$.id" for n in range(21)}

    error_of(case_with_steps({"request": {"method": "GET", "path": "/"}, "capture": capture}))
