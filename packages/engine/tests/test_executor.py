"""The executor, with the network replaced by a function.

httpx2.MockTransport hands every request to a handler instead of sending
it. The handler plays both APIs: requests to old.test get the old API's
answers, requests to new.test the new one's.
"""

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx2
import pytest
from paritylens_engine import DiffKind, NoiseSource, Note, Severity, Verdict
from paritylens_engine.egress import EgressMode, EgressPolicy
from paritylens_engine.executor import Executor, ExecutorSettings
from paritylens_engine.redact import MASK, Redactor
from paritylens_engine.report import RunReport, StepOutcome
from paritylens_engine.suite import Suite

type Handler = Callable[[httpx2.Request], httpx2.Response]

PERMISSIVE = EgressPolicy(mode=EgressMode.PERMISSIVE)


def suite(*cases: dict[str, Any], **extra: Any) -> Suite:
    return Suite.model_validate(
        {
            "targets": {
                "old": {"base_url": "http://old.test"},
                "new": {"base_url": "http://new.test"},
            },
            "cases": list(cases),
            **extra,
        }
    )


def case(*steps: dict[str, Any], name: str = "case", **extra: Any) -> dict[str, Any]:
    return {"name": name, "steps": list(steps), **extra}


def get(path: str, **extra: Any) -> dict[str, Any]:
    return {"request": {"method": "GET", "path": path}, **extra}


def run(handler: Handler, a_suite: Suite, **executor_options: Any) -> RunReport:
    executor_options.setdefault("policy", PERMISSIVE)
    executor = Executor(transport=httpx2.MockTransport(handler), **executor_options)
    return asyncio.run(executor.run(a_suite))


class Recorder:
    """A handler that remembers every request and answers with JSON per host."""

    def __init__(self, old: Any = None, new: Any = None) -> None:
        self.requests: list[httpx2.Request] = []
        self._bodies = {"old.test": old, "new.test": new}

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return httpx2.Response(200, json=self._bodies[request.url.host])

    def sent_to(self, host: str) -> list[httpx2.Request]:
        return [request for request in self.requests if request.url.host == host]


def test_identical_responses_give_a_compatible_case() -> None:
    report = run(Recorder(old={"a": 1}, new={"a": 1}), suite(case(get("/orders"))))

    [result] = report.cases
    assert (result.verdict, result.max_severity) == (Verdict.COMPATIBLE, Severity.NONE)
    assert result.steps[0].outcome is StepOutcome.COMPARED
    assert report.summary.total == report.summary.compatible == 1
    assert (report.old_base_url, report.new_base_url) == ("http://old.test", "http://new.test")


def test_a_difference_reaches_the_report() -> None:
    report = run(Recorder(old={"total": 332}, new={"total": 333}), suite(case(get("/orders/1"))))

    [result] = report.cases
    assert result.verdict is Verdict.BREAKING
    assert result.steps[0].comparison is not None
    [difference] = result.steps[0].comparison.differences
    assert (difference.kind, difference.path, difference.severity) == (
        DiffKind.VALUE_CHANGED,
        "$.total",
        Severity.CRITICAL,
    )


def test_the_old_api_is_called_twice_and_the_new_api_once() -> None:
    recorder = Recorder(old={}, new={})

    run(recorder, suite(case(get("/orders"))))

    assert len(recorder.sent_to("old.test")) == 2
    assert len(recorder.sent_to("new.test")) == 1


def test_noise_detection_can_be_turned_off_per_case() -> None:
    recorder = Recorder(old={}, new={})

    run(recorder, suite(case(get("/orders"), noise_detection=False)))

    assert len(recorder.sent_to("old.test")) == 1


def test_the_request_is_the_same_on_both_sides() -> None:
    recorder = Recorder(old={}, new={})
    step = {
        "request": {
            "method": "POST",
            "path": "/orders",
            "query": {"dry_run": "1"},
            "headers": {"X-Trace": "abc"},
            "json": {"name": "John", "items": [{"sku": "A-100", "quantity": 3}]},
        }
    }

    run(recorder, suite(case(step)))

    [old, _, new] = recorder.sent_to("old.test") + recorder.sent_to("new.test")
    for request in (old, new):
        assert request.method == "POST"
        assert request.url.path == "/orders"
        assert request.url.params["dry_run"] == "1"
        assert request.headers["x-trace"] == "abc"
        assert request.headers["content-type"] == "application/json"
        assert json.loads(request.content) == step["request"]["json"]


def test_headers_from_step_override_target_override_suite() -> None:
    recorder = Recorder(old={}, new={})
    a_suite = Suite.model_validate(
        {
            "headers": {"X-A": "suite", "X-B": "suite", "X-C": "suite"},
            "targets": {
                "old": {"base_url": "http://old.test", "headers": {"X-B": "old", "X-C": "old"}},
                "new": {"base_url": "http://new.test"},
            },
            "cases": [
                case({"request": {"method": "GET", "path": "/", "headers": {"X-C": "step"}}})
            ],
        }
    )

    run(recorder, a_suite)

    old, new = recorder.sent_to("old.test")[0], recorder.sent_to("new.test")[0]
    assert [old.headers[name] for name in ("x-a", "x-b", "x-c")] == ["suite", "old", "step"]
    assert [new.headers[name] for name in ("x-a", "x-b", "x-c")] == ["suite", "suite", "step"]


# --- multi-step cases -----------------------------------------------------------


def stateful_api() -> Handler:
    """Old issues ORD-n IDs, new issues NEW-n. GET returns the order for an ID."""
    counters = {"old.test": 0, "new.test": 0}
    prefixes = {"old.test": "ORD", "new.test": "NEW"}

    def handler(request: httpx2.Request) -> httpx2.Response:
        host = request.url.host
        if request.method == "POST":
            counters[host] += 1
            return httpx2.Response(201, json={"id": f"{prefixes[host]}-{counters[host]}"})
        order_id = request.url.path.rsplit("/", 1)[1]
        if not order_id.startswith(prefixes[host]):
            return httpx2.Response(404, json={"error": "not found"})
        return httpx2.Response(200, json={"id": order_id, "status": "accepted"})

    return handler


CREATE_THEN_FETCH = case(
    {"id": "create", "request": {"method": "POST", "path": "/orders"}, "capture": {"oid": "$.id"}},
    {"id": "fetch", "request": {"method": "GET", "path": "/orders/{{oid}}"}},
)


def test_each_side_uses_the_values_it_captured_itself() -> None:
    """The old API is asked for the old API's order, the new API for its own."""
    report = run(stateful_api(), suite(CREATE_THEN_FETCH))

    [result] = report.cases
    fetch = result.steps[1]
    assert fetch.id == "fetch"
    assert fetch.old.response is not None and fetch.new.response is not None
    assert (fetch.old.response.status, fetch.new.response.status) == (200, 200)
    assert fetch.old.request is not None and fetch.new.request is not None
    assert fetch.old.request.url == "http://old.test/orders/ORD-1"
    assert fetch.new.request.url == "http://new.test/orders/NEW-1"


def test_ids_that_differ_per_call_are_noise_across_steps() -> None:
    report = run(stateful_api(), suite(CREATE_THEN_FETCH))

    [result] = report.cases
    assert result.verdict is Verdict.COMPATIBLE
    for step in result.steps:
        assert step.comparison is not None
        assert {d.noise_source for d in step.comparison.differences} == {NoiseSource.BASELINE}


def test_a_captured_value_is_escaped_in_the_path() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.method == "POST":
            return httpx2.Response(200, json={"id": "a/b?c=d"})
        return httpx2.Response(200, json={"raw_path": request.url.raw_path.decode()})

    report = run(handler, suite(CREATE_THEN_FETCH))

    fetch = report.cases[0].steps[1]
    assert fetch.old.response is not None and fetch.old.response.body is not None
    assert json.loads(fetch.old.response.body) == {"raw_path": "/orders/a%2Fb%3Fc%3Dd"}


def test_a_placeholder_alone_in_a_json_value_keeps_the_captured_type() -> None:
    seen: list[Any] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/orders":
            return httpx2.Response(200, json={"id": 123})
        seen.append(json.loads(request.content))
        return httpx2.Response(200, json={})

    a_case = case(
        {"request": {"method": "POST", "path": "/orders"}, "capture": {"oid": "$.id"}},
        {
            "request": {
                "method": "POST",
                "path": "/payments",
                "json": {"order_id": "{{oid}}", "memo": "order {{oid}}"},
            }
        },
    )

    run(handler, suite(a_case))

    assert seen[0] == {"order_id": 123, "memo": "order 123"}


def test_a_step_whose_variable_was_not_captured_is_skipped_on_that_side() -> None:
    """Old rejects the order, so there is nothing to fetch from old."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.method == "POST":
            if request.url.host == "old.test":
                return httpx2.Response(400, json={"error": "customer_name is required"})
            return httpx2.Response(201, json={"id": "NEW-1"})
        return httpx2.Response(200, json={"id": "NEW-1"})

    report = run(handler, suite(CREATE_THEN_FETCH))

    [result] = report.cases
    create, fetch = result.steps
    assert create.outcome is StepOutcome.COMPARED
    assert fetch.outcome is StepOutcome.SKIPPED
    assert fetch.old.skipped == "variable 'oid' was not captured by an earlier step"
    assert fetch.old.request is None
    assert fetch.new.response is not None  # the new side did run
    # The verdict comes from the step that was compared: 400 versus 201.
    assert (result.verdict, result.max_severity) == (Verdict.BREAKING, Severity.CRITICAL)


# --- failures -------------------------------------------------------------------


def failing_on(host: str, error: Exception) -> Handler:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == host:
            raise error
        return httpx2.Response(200, json={})

    return handler


def test_a_connection_failure_makes_the_case_an_error_not_a_pass() -> None:
    error = httpx2.ConnectError("could not reach http://new.test/orders?token=abc")

    report = run(failing_on("new.test", error), suite(case(get("/orders"))))

    [result] = report.cases
    assert result.verdict is Verdict.ERROR
    assert result.steps[0].outcome is StepOutcome.ERROR
    # The class name only: the exception's message can contain the URL.
    assert result.steps[0].new.error == "request failed: ConnectError"
    assert report.summary.error == 1
    assert report.summary.score is None


def test_a_timeout_is_reported_as_such() -> None:
    report = run(failing_on("old.test", httpx2.ReadTimeout("slow")), suite(case(get("/orders"))))

    assert report.cases[0].steps[0].old.error == "timed out"


def test_a_destination_the_policy_refuses_is_never_contacted() -> None:
    recorder = Recorder(old={}, new={})
    policy = EgressPolicy(mode=EgressMode.ALLOWLIST, allow_hosts=frozenset({"old.test"}))

    report = run(recorder, suite(case(get("/orders"))), policy=policy)

    step = report.cases[0].steps[0]
    assert step.new.error == "blocked by egress policy: host 'new.test' is not on the allowlist"
    assert recorder.sent_to("new.test") == []
    assert report.cases[0].verdict is Verdict.ERROR


def test_a_failed_baseline_request_does_not_fail_the_case() -> None:
    calls = {"old.test": 0}

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "old.test":
            calls["old.test"] += 1
            if calls["old.test"] == 2:
                raise httpx2.ConnectError("flaky")
        return httpx2.Response(200, json={"a": 1})

    report = run(handler, suite(case(get("/orders"))))

    [result] = report.cases
    assert result.verdict is Verdict.COMPATIBLE
    assert result.steps[0].comparison is not None
    assert result.steps[0].comparison.notes == (Note.BASELINE_UNAVAILABLE,)


def test_redirects_are_recorded_not_followed() -> None:
    requests: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(str(request.url))
        return httpx2.Response(302, headers={"location": "http://169.254.169.254/latest/"})

    report = run(handler, suite(case(get("/go"), noise_detection=False)))

    assert requests == ["http://old.test/go", "http://new.test/go"]
    step = report.cases[0].steps[0]
    assert step.old.response is not None
    assert step.old.response.status == 302


# --- size limits ----------------------------------------------------------------


def test_a_body_over_the_limit_is_cut_and_the_case_is_not_called_compatible() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, text="x" * 5000)

    report = run(handler, suite(case(get("/big"))), settings=ExecutorSettings(max_body_bytes=1000))

    [result] = report.cases
    step = result.steps[0]
    assert step.old.response is not None and step.old.response.body is not None
    assert step.old.response.body_truncated
    assert len(step.old.response.body) == 1000
    assert step.comparison is not None
    assert Note.BODY_NOT_COMPARED_TRUNCATED in step.comparison.notes
    # No differences were found, but only because nothing was compared.
    assert result.verdict is Verdict.WARNING


def test_the_report_keeps_less_of_a_body_than_the_comparison_saw() -> None:
    padding = "x" * 3000

    def handler(request: httpx2.Request) -> httpx2.Response:
        tail = 1 if request.url.host == "old.test" else 2
        return httpx2.Response(200, json={"padding": padding, "tail": tail})

    report = run(
        handler, suite(case(get("/big"))), settings=ExecutorSettings(max_stored_body_bytes=100)
    )

    step = report.cases[0].steps[0]
    assert step.old.response is not None and step.old.response.body is not None
    assert len(step.old.response.body) == 100
    assert step.old.response.body_truncated
    # The difference sits beyond what was stored and was still found.
    assert step.comparison is not None
    assert [d.path for d in step.comparison.differences] == ["$.tail"]


# --- secrets --------------------------------------------------------------------


def test_credentials_do_not_reach_the_report() -> None:
    secret = "s3cr3t-token-value"

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.headers["authorization"] == f"Bearer {secret}"  # really sent
        return httpx2.Response(
            200,
            headers={"set-cookie": "session=abc123"},
            json={"echo": request.headers["authorization"]},
        )

    a_suite = suite(
        case(get("/whoami", request={"method": "GET", "path": "/whoami", "query": {"k": secret}})),
        headers={"Authorization": f"Bearer {secret}"},
    )

    report = run(handler, a_suite, redactor=Redactor([secret]))

    dumped = report.model_dump_json()
    assert secret not in dumped
    assert "abc123" not in dumped
    step = report.cases[0].steps[0]
    assert step.old.request is not None and step.old.response is not None
    assert step.old.request.headers["authorization"] == MASK
    assert step.old.response.headers["set-cookie"] == MASK


# --- time and ordering -----------------------------------------------------------


def test_request_time_timestamps_are_noise_end_to_end() -> None:
    """One-second timestamps that the baseline cannot tell apart."""
    now = datetime(2026, 10, 2, 1, 0, 0, tzinfo=UTC)

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "old.test":
            return httpx2.Response(200, json={"created_at": "2026-10-02T10:00:00+09:00"})
        return httpx2.Response(200, json={"created_at": "2026-10-02T01:00:00.250Z"})

    report = run(handler, suite(case(get("/orders/1"))), now=lambda: now)

    [result] = report.cases
    assert result.verdict is Verdict.COMPATIBLE
    assert result.steps[0].comparison is not None
    [difference] = result.steps[0].comparison.differences
    assert difference.noise_source is NoiseSource.CLOCK
    assert (report.started_at, report.finished_at) == (now, now)


def test_cases_are_reported_in_suite_order_whatever_order_they_finish_in() -> None:
    names = [f"case-{n}" for n in range(12)]
    cases = [case(get(f"/{name}"), name=name, noise_detection=False) for name in names]

    report = run(Recorder(old={}, new={}), suite(*cases), settings=ExecutorSettings(concurrency=5))

    assert [result.name for result in report.cases] == names


def test_the_summary_counts_every_verdict() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/broken" and request.url.host == "new.test":
            return httpx2.Response(500, json={})
        if request.url.path == "/down" and request.url.host == "new.test":
            raise httpx2.ConnectError("down")
        value = "x" if request.url.host == "old.test" or request.url.path == "/same" else "y"
        return httpx2.Response(200, json={"name": value})

    report = run(
        handler,
        suite(
            case(get("/same"), name="same"),
            case(get("/changed"), name="changed"),
            case(get("/broken"), name="broken"),
            case(get("/down"), name="down"),
        ),
    )

    assert [c.verdict for c in report.cases] == [
        Verdict.COMPATIBLE,
        Verdict.WARNING,
        Verdict.BREAKING,
        Verdict.ERROR,
    ]
    summary = report.summary
    assert (summary.total, summary.evaluated) == (4, 3)
    assert summary.score == pytest.approx(1 / 3)


def test_a_report_round_trips_through_json() -> None:
    report = run(stateful_api(), suite(CREATE_THEN_FETCH))

    assert RunReport.model_validate_json(report.model_dump_json()) == report


def test_the_clock_is_read_for_each_response() -> None:
    ticks = iter(datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=n) for n in range(100))

    report = run(Recorder(old={}, new={}), suite(case(get("/"))), now=lambda: next(ticks))

    step = report.cases[0].steps[0]
    assert step.old.response is not None and step.new.response is not None
    assert step.old.response.received_at is not None
    assert report.started_at < step.old.response.received_at < report.finished_at


def test_a_secret_with_special_characters_is_masked_in_the_recorded_url_and_body() -> None:
    secret = 'p@ss "word"/+'
    step = {
        "request": {
            "method": "POST",
            "path": "/login",
            "query": {"key": secret},
            "json": {"password": secret},
        }
    }

    report = run(Recorder(old={}, new={}), suite(case(step)), redactor=Redactor([secret]))

    dumped = report.model_dump_json()
    assert "p@ss" not in dumped
    assert "p%40ss" not in dumped
    request = report.cases[0].steps[0].old.request
    assert request is not None
    assert MASK in request.url
    assert request.body is not None and MASK in request.body


# --- found in review: credentials -------------------------------------------------


def test_differences_are_redacted_like_everything_else() -> None:
    secret = "s3cr3t-token-value"

    def handler(request: httpx2.Request) -> httpx2.Response:
        old = request.url.host == "old.test"
        return httpx2.Response(
            200,
            headers={"set-cookie": "session=abc123" if old else "session=zzz999"},
            json={"echo": request.headers["authorization"] if old else None},
        )

    a_suite = suite(
        case(get("/whoami")),
        headers={"Authorization": f"Bearer {secret}"},
        rules={"compare_headers": ["set-cookie"]},
    )

    report = run(handler, a_suite, redactor=Redactor([secret]))

    dumped = report.model_dump_json()
    assert secret not in dumped
    assert "abc123" not in dumped and "zzz999" not in dumped
    comparison = report.cases[0].steps[0].comparison
    assert comparison is not None
    by_path = {d.path: d for d in comparison.differences}
    # The findings themselves survive; only the values are masked.
    assert by_path["$.echo"].old == f"Bearer {MASK}"
    assert (by_path["header.set-cookie"].old, by_path["header.set-cookie"].new) == (MASK, MASK)


@pytest.mark.parametrize("secret", ["pa+ss/word@x", "a=b&c;d", "p(a)ss!$'*,:"])
def test_a_secret_in_the_path_is_masked_however_the_client_encodes_it(secret: str) -> None:
    report = run(
        Recorder(old={}, new={}), suite(case(get(f"/x/{secret}/y"))), redactor=Redactor([secret])
    )

    request = report.cases[0].steps[0].old.request
    assert request is not None
    assert request.url == f"http://old.test/x/{MASK}/y"
    assert secret not in report.model_dump_json()


def test_a_capture_marked_secret_is_masked_everywhere_it_goes() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        token = f"tok-{request.url.host}-9f8e7d"
        if request.url.path == "/login":
            return httpx2.Response(200, json={"access_token": token, "user": "john"})
        return httpx2.Response(200, json={"seen": request.headers.get("x-session")})

    login_then_use = case(
        {
            "request": {"method": "POST", "path": "/login"},
            "capture": {"token": {"path": "$.access_token", "secret": True}},
        },
        {
            "request": {
                "method": "GET",
                "path": "/me",
                "query": {"access_token": "{{token}}"},
                "headers": {"X-Session": "{{token}}"},
            }
        },
    )

    report = run(handler, suite(login_then_use))

    dumped = report.model_dump_json()
    assert "9f8e7d" not in dumped
    assert '"user\\":\\"john\\"' in dumped or "john" in dumped  # the rest of the body is kept
    use = report.cases[0].steps[1]
    assert use.old.request is not None
    assert use.old.request.url == f"http://old.test/me?access_token={MASK}"
    assert use.old.request.headers["x-session"] == MASK


def test_a_capture_not_marked_secret_is_left_readable() -> None:
    report = run(stateful_api(), suite(CREATE_THEN_FETCH))

    assert "ORD-1" in report.model_dump_json()


def test_a_secret_captured_in_one_case_is_not_masked_in_another() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"value": "shared-text"})

    capturing = case(
        {
            "request": {"method": "GET", "path": "/a"},
            "capture": {"v": {"path": "$.value", "secret": True}},
        },
        name="capturing",
    )
    plain = case(get("/b"), name="plain")

    report = run(handler, suite(capturing, plain))

    bodies = {c.name: c.steps[0].old.response.body for c in report.cases if c.steps[0].old.response}
    assert bodies == {"capturing": f'{{"value":"{MASK}"}}', "plain": '{"value":"shared-text"}'}


# --- found in review: one bad case must not abort the run ---------------------------


def test_a_request_that_cannot_be_built_fails_its_own_case_only() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"name": "日本語"})

    # The captured value is not ASCII, so it cannot go into a header.
    broken = case(
        {"request": {"method": "GET", "path": "/a"}, "capture": {"name": "$.name"}},
        {"request": {"method": "GET", "path": "/b", "headers": {"X-Name": "{{name}}"}}},
        name="broken",
    )
    fine = case(get("/c"), name="fine")

    report = run(handler, suite(broken, fine))

    by_name = {c.name: c for c in report.cases}
    assert by_name["fine"].verdict is Verdict.COMPATIBLE
    assert by_name["broken"].verdict is Verdict.ERROR
    assert by_name["broken"].steps[1].old.error == "request failed: UnicodeEncodeError"


@pytest.mark.parametrize("charset", ["undefined", "idna", "no-such-charset", "rot13"])
def test_a_nonsense_charset_from_the_server_does_not_abort_the_run(charset: str) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200, headers={"content-type": f"text/plain; charset={charset}"}, content=b"hello"
        )

    report = run(handler, suite(case(get("/"))))

    response = report.cases[0].steps[0].old.response
    assert response is not None
    assert response.body == "hello"


def test_a_failed_request_outranks_a_skipped_one() -> None:
    """Old cannot run step 2; new runs it and fails. That is an error, not a skip."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.method == "POST":
            return httpx2.Response(200, json={} if request.url.host == "old.test" else {"id": 1})
        raise httpx2.ConnectError("down")

    report = run(handler, suite(CREATE_THEN_FETCH))

    [result] = report.cases
    assert result.steps[1].outcome is StepOutcome.ERROR
    assert result.verdict is Verdict.ERROR
    assert report.summary.error == 1


# --- found in review: isolation and captures ----------------------------------------


def test_cookies_are_not_carried_from_one_request_to_the_next() -> None:
    seen: list[str | None] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.headers.get("cookie"))
        return httpx2.Response(200, headers={"set-cookie": "session=abc; Path=/"}, json={})

    run(handler, suite(case(get("/login"), get("/anonymous")), case(get("/other"))))

    assert seen
    assert set(seen) == {None}


def test_a_value_can_be_captured_from_an_array_element_found_by_key() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/items":
            return httpx2.Response(
                200, json={"items": [{"sku": "B-200", "id": 7}, {"sku": "A-100", "id": 9}]}
            )
        return httpx2.Response(200, json={"path": request.url.path})

    a_case = case(
        {"request": {"method": "GET", "path": "/items"}, "capture": {"v": "$.items[sku=A-100].id"}},
        get("/items/{{v}}"),
    )

    report = run(handler, suite(a_case))

    request = report.cases[0].steps[1].old.request
    assert request is not None
    assert request.url == "http://old.test/items/9"


@pytest.mark.parametrize("value", ["..", ".", ""])
def test_a_captured_value_that_would_change_the_path_is_refused(value: str) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"id": value})

    a_case = case(
        {"request": {"method": "GET", "path": "/users"}, "capture": {"v": "$.id"}},
        {"request": {"method": "DELETE", "path": "/users/{{v}}/admin"}},
    )

    report = run(handler, suite(a_case))

    step = report.cases[0].steps[1]
    assert step.outcome is StepOutcome.ERROR
    assert step.old.request is None  # nothing was sent
    assert step.old.error is not None and "cannot be used in a path" in step.old.error


def test_a_captured_null_counts_as_not_captured() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"id": None})

    report = run(handler, suite(CREATE_THEN_FETCH))

    assert report.cases[0].steps[1].outcome is StepOutcome.SKIPPED


def test_an_oversized_captured_value_counts_as_not_captured() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"id": "x" * 100_000})

    report = run(handler, suite(CREATE_THEN_FETCH))

    assert report.cases[0].steps[1].outcome is StepOutcome.SKIPPED


def test_nul_characters_do_not_reach_the_report() -> None:
    """PostgreSQL cannot store them, and the report is headed there."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        value = "a\x00b" if request.url.host == "old.test" else "a\x00c"
        return httpx2.Response(200, json={"v": value})

    report = run(handler, suite(case(get("/"), noise_detection=False)))

    comparison = report.cases[0].steps[0].comparison
    assert comparison is not None
    [difference] = comparison.differences
    assert (difference.old, difference.new) == ("a\ufffdb", "a\ufffdc")
