"""Sends a suite's requests to both APIs and builds the RunReport.

This is the only module in the engine that performs I/O. Everything it
learns from the network is handed to compare_step as plain values.

async, briefly: each request spends nearly all its time waiting for the
network. `await` gives control back to the event loop while waiting, so a
single thread can have many requests in flight. Nothing here runs in
parallel in the CPU sense; the waiting overlaps.
"""

import asyncio
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from http.cookiejar import CookieJar
from urllib.parse import quote

import httpx2
from pydantic import JsonValue

from paritylens_engine import __version__
from paritylens_engine.compare import compare_step
from paritylens_engine.egress import EgressDeniedError, EgressPolicy
from paritylens_engine.jsonvalue import InvalidJsonError, Json, label, parse_json
from paritylens_engine.model import (
    Difference,
    DiffKind,
    Note,
    ResponseSnapshot,
    RuleSet,
    Severity,
    StepComparison,
    Verdict,
)
from paritylens_engine.paths import parse_pattern
from paritylens_engine.redact import MASK, Redactor, is_sensitive_header
from paritylens_engine.report import (
    CaseResult,
    RequestSnapshot,
    RunReport,
    SideResult,
    StepOutcome,
    StepResult,
)
from paritylens_engine.suite import Case, Step, Suite, Target
from paritylens_engine.template import MissingVariableError, placeholders, render_text, render_value
from paritylens_engine.transport import GuardedTransport
from paritylens_engine.verdict import summarize, verdict_for

# A captured value longer than this is not kept as a variable. IDs and
# tokens are short; a megabyte of text is a mistake in the capture path.
MAX_CAPTURED_CHARS = 8192


@dataclass(frozen=True)
class ExecutorSettings:
    connect_timeout: float = 5.0
    # For one request, start to finish, including reading the body.
    request_timeout: float = 30.0
    # Bodies are read up to this size and compared only if complete.
    max_body_bytes: int = 1024 * 1024
    # A report keeps this much of each body. Comparison uses the full one.
    max_stored_body_bytes: int = 64 * 1024
    # How many cases are in flight at once.
    concurrency: int = 4
    user_agent: str = f"paritylens/{__version__}"


@dataclass
class _Exchange:
    """One step on one side, with the full response still attached."""

    request: RequestSnapshot | None = None
    response: ResponseSnapshot | None = None
    error: str | None = None
    skipped: str | None = None


@dataclass
class _Track:
    """One pass through a case's steps against one target."""

    target: Target
    variables: dict[str, Json] = field(default_factory=dict)
    exchanges: list[_Exchange] = field(default_factory=list)


@dataclass(frozen=True)
class _PreparedRequest:
    method: str
    url: str
    query: dict[str, str]
    headers: dict[str, str]
    content: str | None


class _RequestNotSendableError(Exception):
    """The request cannot be built from the values captured so far."""


class _NoCookies(CookieJar):
    """A cookie jar that never stores anything.

    One HTTP client serves every case and both APIs. If it kept cookies,
    a session set by one case would be sent with the next, and the old
    API's cookies would go to the new API whenever the two share a host.
    Each request must carry only what the suite says it carries.
    """

    def extract_cookies(self, response: object, request: object) -> None:
        return None


def _utc_now() -> datetime:
    return datetime.now(UTC)


class Executor:
    def __init__(
        self,
        *,
        policy: EgressPolicy,
        settings: ExecutorSettings | None = None,
        redactor: Redactor | None = None,
        transport: httpx2.AsyncBaseTransport | None = None,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._policy = policy
        self._settings = settings or ExecutorSettings()
        self._redactor = redactor or Redactor()
        # Tests pass a mock transport; real runs get the guarded one.
        self._transport = transport
        self._now = now

    async def run(self, suite: Suite) -> RunReport:
        started_at = self._now()
        limit = asyncio.Semaphore(self._settings.concurrency)
        # Each case sends on up to three tracks at once. A smaller pool
        # would leave requests queueing for a connection while their
        # timeout runs.
        transport = self._transport or GuardedTransport(
            self._policy, max_connections=3 * self._settings.concurrency
        )

        async with httpx2.AsyncClient(
            transport=transport,
            # A redirect is part of the behaviour under test, so it is
            # recorded as the response. Following it would also let a
            # target bounce the request to a place the policy never saw.
            follow_redirects=False,
            trust_env=False,
            timeout=httpx2.Timeout(
                self._settings.request_timeout, connect=self._settings.connect_timeout
            ),
        ) as client:
            client.cookies.jar = _NoCookies()

            async def run_limited(case: Case) -> CaseResult:
                async with limit:
                    return await self._run_case(client, suite, case)

            # gather keeps results in the order of the cases, whatever
            # order they finish in.
            cases = await asyncio.gather(*(run_limited(case) for case in suite.cases))

        return RunReport(
            engine_version=__version__,
            started_at=started_at,
            finished_at=self._now(),
            old_base_url=self._redactor.text(suite.targets.old.base_url),
            new_base_url=self._redactor.text(suite.targets.new.base_url),
            rules=suite.rules,
            summary=summarize(case.verdict for case in cases),
            cases=tuple(cases),
        )

    async def _run_case(self, client: httpx2.AsyncClient, suite: Suite, case: Case) -> CaseResult:
        # Secrets captured while this case runs are masked in this case's
        # results. They are added to a copy so they do not accumulate
        # across the run.
        redactor = self._redactor.child()

        old = _Track(suite.targets.old)
        new = _Track(suite.targets.new)
        # The baseline is the old API again: same target, separate
        # variables, so its captured IDs do not mix with the first pass.
        baseline = _Track(suite.targets.old) if case.noise_detection else None

        tracks = [track for track in (old, new, baseline) if track is not None]
        await asyncio.gather(
            *(self._run_track(client, suite, case, track, redactor) for track in tracks)
        )

        steps = tuple(
            self._step_result(
                case.step_id(index),
                old.exchanges[index],
                new.exchanges[index],
                baseline.exchanges[index] if baseline else None,
                suite.rules,
                redactor,
            )
            for index in range(len(case.steps))
        )
        verdict, max_severity = _judge_case(steps)
        return CaseResult(name=case.name, verdict=verdict, max_severity=max_severity, steps=steps)

    async def _run_track(
        self,
        client: httpx2.AsyncClient,
        suite: Suite,
        case: Case,
        track: _Track,
        redactor: Redactor,
    ) -> None:
        for step in case.steps:
            exchange = await self._run_step(client, suite, step, track, redactor)
            track.exchanges.append(exchange)
            if exchange.response is not None:
                for name, value in _capture(step, exchange.response).items():
                    track.variables[name] = value
                    if step.capture[name].secret:
                        redactor.add(_as_secret_text(value))

    async def _run_step(
        self,
        client: httpx2.AsyncClient,
        suite: Suite,
        step: Step,
        track: _Track,
        redactor: Redactor,
    ) -> _Exchange:
        try:
            request = _build_request(
                suite, track.target, step, track.variables, self._settings.user_agent
            )
        except MissingVariableError as exc:
            return _Exchange(skipped=f"variable {exc.name!r} was not captured by an earlier step")
        except _RequestNotSendableError as exc:
            return _Exchange(error=str(exc))

        snapshot = _snapshot(request, redactor)
        try:
            return await self._send(client, request, snapshot)
        except EgressDeniedError as exc:
            return _Exchange(request=snapshot, error=f"blocked by egress policy: {exc}")
        except (TimeoutError, httpx2.TimeoutException):
            return _Exchange(request=snapshot, error="timed out")
        except Exception as exc:
            # Deliberately broad. One request that cannot be sent (a
            # captured value that is not valid in a header, a URL the
            # client rejects) must fail its own case and nothing else;
            # an exception escaping here would abort the whole run.
            # Only the class name is recorded: the message can contain
            # the URL or a header value.
            return _Exchange(request=snapshot, error=f"request failed: {type(exc).__name__}")

    async def _send(
        self, client: httpx2.AsyncClient, request: _PreparedRequest, snapshot: RequestSnapshot
    ) -> _Exchange:
        self._policy.check_url(request.url)
        started = time.perf_counter()
        async with (
            asyncio.timeout(self._settings.request_timeout),
            client.stream(
                request.method,
                request.url,
                params=request.query or None,
                headers=request.headers,
                content=request.content,
            ) as response,
        ):
            body, truncated = await self._read_body(response)
        duration_ms = (time.perf_counter() - started) * 1000

        return _Exchange(
            request=snapshot,
            response=ResponseSnapshot(
                status=response.status_code,
                headers=dict(response.headers),
                body=body or None,
                body_truncated=truncated,
                duration_ms=round(duration_ms, 1),
                received_at=self._now(),
            ),
        )

    async def _read_body(self, response: httpx2.Response) -> tuple[str, bool]:
        """Read the body up to the size limit. Returns (text, was_cut_short)."""
        limit = self._settings.max_body_bytes
        chunks: list[bytes] = []
        size = 0
        truncated = False
        # aiter_bytes yields decompressed data, so the limit also bounds
        # what a small compressed response can expand to.
        async for chunk in response.aiter_bytes():
            if size + len(chunk) > limit:
                chunks.append(chunk[: limit - size])
                truncated = True
                break
            chunks.append(chunk)
            size += len(chunk)
        raw = b"".join(chunks)
        try:
            text = raw.decode(response.charset_encoding or "utf-8", errors="replace")
        except (LookupError, ValueError):
            # The server named a charset that does not exist, or one that
            # is not a text encoding at all.
            text = raw.decode("utf-8", errors="replace")
        return text, truncated

    def _step_result(
        self,
        step_id: str,
        old: _Exchange,
        new: _Exchange,
        baseline: _Exchange | None,
        rules: RuleSet,
        redactor: Redactor,
    ) -> StepResult:
        comparison: StepComparison | None = None
        # A failed request outranks a skipped one: "could not reach the
        # API" must never be reported as merely "not run".
        if old.error or new.error:
            outcome = StepOutcome.ERROR
        elif old.response is None or new.response is None:
            outcome = StepOutcome.SKIPPED
        else:
            outcome = StepOutcome.COMPARED
            baseline_response = baseline.response if baseline else None
            comparison = compare_step(
                old.response, new.response, rules=rules, baseline=baseline_response
            )
            notes = comparison.notes
            if baseline is not None and baseline_response is None:
                notes = (*notes, Note.BASELINE_UNAVAILABLE)
            # The comparison ran on the real responses. What it found is
            # about to be stored, so it is masked like everything else.
            comparison = StepComparison(
                differences=tuple(_redacted(d, redactor) for d in comparison.differences),
                notes=notes,
            )
        return StepResult(
            id=step_id,
            outcome=outcome,
            old=self._stored(old, redactor),
            new=self._stored(new, redactor),
            comparison=comparison,
        )

    def _stored(self, exchange: _Exchange, redactor: Redactor) -> SideResult:
        """The form of an exchange that goes into the report: redacted and size-limited."""
        response = exchange.response
        if response is not None:
            body = response.body
            clipped = response.body_truncated
            if body is not None:
                body = _storable(redactor.text(body))
                if len(body) > self._settings.max_stored_body_bytes:
                    body = body[: self._settings.max_stored_body_bytes]
                    clipped = True
            response = response.model_copy(
                update={
                    "headers": redactor.headers(response.headers),
                    "body": body,
                    "body_truncated": clipped,
                }
            )
        return SideResult(
            request=exchange.request,
            response=response,
            error=redactor.text(exchange.error) if exchange.error else None,
            skipped=redactor.text(exchange.skipped) if exchange.skipped else None,
        )


def _build_request(
    suite: Suite, target: Target, step: Step, variables: dict[str, Json], user_agent: str
) -> _PreparedRequest:
    spec = step.request
    # Values going into the path are escaped so that a captured ID
    # containing "/" or "?" stays one path segment. Only the variables the
    # path actually uses are rendered.
    escaped: dict[str, Json] = {}
    for name in placeholders(spec.path):
        text = render_text("{{" + name + "}}", variables)
        if text in ("", ".", ".."):
            # These would change which resource the path names instead of
            # filling in a segment of it.
            raise _RequestNotSendableError(
                f"variable {name!r} cannot be used in a path: its value is empty or a dot segment"
            )
        escaped[name] = quote(text, safe="")
    path = render_text(spec.path, escaped)

    headers = {"user-agent": user_agent}
    for source in (suite.headers, target.headers, spec.headers):
        headers.update(
            {name.lower(): render_text(value, variables) for name, value in source.items()}
        )

    content: str | None = None
    if spec.json_body is not None:
        content = json.dumps(render_value(spec.json_body, variables), ensure_ascii=False)
        headers.setdefault("content-type", "application/json")
    elif spec.body is not None:
        content = render_text(spec.body, variables)

    return _PreparedRequest(
        method=spec.method,
        url=target.base_url + path,
        query={name: render_text(value, variables) for name, value in spec.query.items()},
        headers=headers,
        content=content,
    )


def _snapshot(request: _PreparedRequest, redactor: Redactor) -> RequestSnapshot:
    """The record of a request for the report.

    The URL is written out from its redacted parts instead of taken from
    the HTTP client. The client percent-encodes in its own way, and a
    secret must be masked before any encoding changes how it looks.
    """
    url = redactor.text(request.url)
    if request.query:
        pairs = "&".join(f"{name}={redactor.text(value)}" for name, value in request.query.items())
        url = f"{url}?{pairs}"
    return RequestSnapshot(
        method=request.method,
        url=_storable(url),
        headers=redactor.headers(request.headers),
        body=_storable(redactor.text(request.content)) if request.content is not None else None,
    )


def _capture(step: Step, response: ResponseSnapshot) -> dict[str, Json]:
    """Read the step's capture paths from a response.

    A path that is not there, holds null, or holds something too large
    yields no variable; the step that needs it is then skipped.
    """
    if not step.capture or response.body is None or response.body_truncated:
        return {}
    try:
        document = parse_json(response.body)
    except InvalidJsonError:
        return {}
    captured: dict[str, Json] = {}
    for name, capture in step.capture.items():
        found, value = parse_pattern(capture.path).find(document)
        if not found or value is None:
            continue
        if isinstance(value, str) and len(value) > MAX_CAPTURED_CHARS:
            continue
        if isinstance(value, list | dict) and len(json.dumps(value, default=str)) > (
            MAX_CAPTURED_CHARS
        ):
            continue
        captured[name] = value
    return captured


def _as_secret_text(value: Json) -> str:
    if isinstance(value, bool | int | Decimal | str):
        return label(value)
    return ""


def _storable(text: str) -> str:
    # PostgreSQL cannot store a NUL character in text or JSON.
    return text.replace("\x00", "�")


def _storable_value(value: JsonValue) -> JsonValue:
    if isinstance(value, str):
        return _storable(value)
    if isinstance(value, list):
        return [_storable_value(item) for item in value]
    if isinstance(value, dict):
        return {_storable(key): _storable_value(item) for key, item in value.items()}
    return value


def _redacted(difference: Difference, redactor: Redactor) -> Difference:
    """A difference with credentials masked in its values and its path."""
    old, new = redactor.value(difference.old), redactor.value(difference.new)
    if difference.kind is DiffKind.HEADER_CHANGED and is_sensitive_header(
        difference.path.removeprefix("header.")
    ):
        # The header differs and that is worth knowing; what it held is not.
        old = MASK if old is not None else None
        new = MASK if new is not None else None
    return difference.model_copy(
        update={
            "path": _storable(redactor.text(difference.path)),
            "old": _storable_value(old),
            "new": _storable_value(new),
            "detail": redactor.text(difference.detail) if difference.detail else None,
        }
    )


def _judge_case(steps: tuple[StepResult, ...]) -> tuple[Verdict, Severity]:
    compared = [step.comparison for step in steps if step.comparison is not None]
    max_severity = max(
        (comparison.max_severity for comparison in compared),
        key=lambda severity: severity.rank,
        default=Severity.NONE,
    )
    # A failed request, or nothing compared at all, means the case gives
    # no evidence about compatibility. That is not the same as passing.
    if not compared or any(step.outcome is StepOutcome.ERROR for step in steps):
        return Verdict.ERROR, max_severity

    verdict = verdict_for(max_severity)
    # A body too large to compare was not shown to be compatible.
    unverified = any(Note.BODY_NOT_COMPARED_TRUNCATED in c.notes for c in compared)
    if verdict is Verdict.COMPATIBLE and unverified:
        verdict = Verdict.WARNING
    return verdict, max_severity
