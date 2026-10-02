"""A test suite: which two APIs to compare, and what to send them.

The same structure is written as YAML for the CLI and stored as JSON by
the API. Everything that can be checked without sending a request is
checked here, when the suite is loaded: a typo in a variable name should
fail before the run starts, not at step three of case forty.
"""

import re
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

import httpx2
from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from paritylens_engine.model import RuleSet
from paritylens_engine.paths import PathSyntaxError, parse_pattern
from paritylens_engine.template import placeholders

MAX_STEPS_PER_CASE = 20
MAX_CASES_PER_SUITE = 500
MAX_CAPTURES_PER_STEP = 20
MAX_PATH_CHARS = 2000

type HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]

# RFC 9110 "token": the characters a header name may consist of.
_HEADER_NAME = re.compile(r"[A-Za-z0-9!#$%&'*+.^_`|~-]+")
# Printable ASCII and tab. HTTP headers are sent as ASCII; anything else
# would fail when the request is built.
_HEADER_VALUE = re.compile(r"[\t\x20-\x7e]*")
# Headers the HTTP client sets itself. Overriding Host in particular would
# ask the server that was checked for a site that was not.
_RESERVED_HEADERS = frozenset(
    {"host", "content-length", "transfer-encoding", "connection", "upgrade", "te", "trailer"}
)
_UNSAFE_IN_URL = re.compile(r"[\x00-\x20\x7f?#]")


class _Frozen(BaseModel):
    # hide_input_in_errors: a validation error must not repeat the value it
    # rejected. A suite holds credentials (headers, URLs), and error text
    # ends up in terminals and logs.
    model_config = ConfigDict(
        frozen=True, extra="forbid", populate_by_name=True, hide_input_in_errors=True
    )


def _valid_headers(headers: dict[str, str]) -> dict[str, str]:
    for name, value in headers.items():
        if not _HEADER_NAME.fullmatch(name):
            raise ValueError("a header name contains characters that are not allowed")
        if name.lower() in _RESERVED_HEADERS:
            raise ValueError(f"the {name} header is set automatically and cannot be overridden")
        if not _HEADER_VALUE.fullmatch(value):
            raise ValueError(f"the value of header {name} must be printable ASCII")
    return headers


def _fixed_headers(headers: dict[str, str]) -> dict[str, str]:
    """Headers that apply to a whole suite or target: no placeholders.

    They are sent with the very first request, before any step has
    captured anything, so a placeholder there could never be filled in.
    """
    _valid_headers(headers)
    for name, value in headers.items():
        if placeholders(value):
            raise ValueError(f"header {name}: placeholders can only be used in a step's headers")
    return headers


type Headers = Annotated[dict[str, str], AfterValidator(_valid_headers)]
type FixedHeaders = Annotated[dict[str, str], AfterValidator(_fixed_headers)]


class RequestSpec(_Frozen):
    method: HttpMethod
    # Relative to the target's base URL. May contain {{placeholders}}.
    path: str = Field(max_length=MAX_PATH_CHARS)
    query: dict[str, str] = Field(default_factory=dict)
    headers: Headers = Field(default_factory=dict)
    # At most one of these two. "json" is the name used in suite files.
    json_body: JsonValue = Field(default=None, alias="json")
    body: str | None = None

    @field_validator("method", mode="before")
    @classmethod
    def _uppercase_method(cls, method: object) -> object:
        return method.upper() if isinstance(method, str) else method

    @field_validator("path")
    @classmethod
    def _path_is_a_plain_relative_path(cls, path: str) -> str:
        if not path.startswith("/"):
            raise ValueError("path must start with '/'")
        if _UNSAFE_IN_URL.search(path):
            raise ValueError(
                "path must not contain spaces, control characters, '?' or '#'; "
                "put query parameters under 'query'"
            )
        try:
            httpx2.URL("http://host.invalid" + path)
        except httpx2.InvalidURL as exc:
            raise ValueError("path is not a valid URL path") from exc
        return path

    @model_validator(mode="after")
    def _one_body_at_most(self) -> Self:
        if self.json_body is not None and self.body is not None:
            raise ValueError("give either 'json' or 'body', not both")
        return self

    def placeholders(self) -> set[str]:
        used = placeholders(self.path) | placeholders(self.json_body)
        used |= placeholders(self.body) if self.body else set()
        for mapping in (self.query, self.headers):
            for value in mapping.values():
                used |= placeholders(value)
        return used


def _concrete_path(path: str) -> str:
    try:
        pattern = parse_pattern(path)
    except PathSyntaxError as exc:
        raise ValueError(str(exc)) from exc
    if not path.strip().startswith("$") or not pattern.is_concrete:
        raise ValueError("a capture path must name one place, like $.id or $.items[0].id")
    return path


type CapturePath = Annotated[str, AfterValidator(_concrete_path)]
type VariableName = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]


class Capture(_Frozen):
    """Where to read a variable from a step's JSON response."""

    path: CapturePath
    # Treat the captured value as a credential: mask it everywhere in the
    # report. For tokens returned by a login step.
    secret: bool = False


def _expand_capture_shorthand(value: object) -> object:
    # `order_id: $.id` is short for `order_id: {path: $.id}`.
    return {"path": value} if isinstance(value, str) else value


class Step(_Frozen):
    id: str | None = None
    request: RequestSpec
    capture: dict[VariableName, Annotated[Capture, BeforeValidator(_expand_capture_shorthand)]] = (
        Field(default_factory=dict, max_length=MAX_CAPTURES_PER_STEP)
    )


class Case(_Frozen):
    name: str = Field(min_length=1)
    steps: tuple[Step, ...] = Field(min_length=1, max_length=MAX_STEPS_PER_CASE)
    # Send every request to the old API twice to learn which values change
    # on their own. Turn off for requests that must not be repeated.
    noise_detection: bool = True

    @model_validator(mode="after")
    def _variables_are_captured_before_use(self) -> Self:
        captured: set[str] = set()
        for number, step in enumerate(self.steps, start=1):
            missing = step.request.placeholders() - captured
            if missing:
                names = ", ".join(sorted(missing))
                raise ValueError(
                    f"case {self.name!r}, step {number}: {names} used before a step captures it"
                )
            captured |= set(step.capture)
        return self

    @model_validator(mode="after")
    def _step_ids_are_unique(self) -> Self:
        ids = [self.step_id(index) for index in range(len(self.steps))]
        if len(ids) != len(set(ids)):
            raise ValueError(f"case {self.name!r}: step ids must be unique")
        return self

    def step_id(self, index: int) -> str:
        return self.steps[index].id or f"step-{index + 1}"


class Target(_Frozen):
    base_url: str
    # Sent with every request to this target, e.g. different credentials
    # for the old and the new system.
    headers: FixedHeaders = Field(default_factory=dict)

    @field_validator("base_url")
    @classmethod
    def _base_url_is_plain_http(cls, url: str) -> str:
        # The messages do not repeat the URL: it may contain a password,
        # which is exactly the case being rejected.
        if _UNSAFE_IN_URL.search(url):
            raise ValueError(
                "base_url must not contain spaces, control characters, a query or a fragment"
            )
        try:
            parts = urlsplit(url)
            httpx2.URL(url)
        except (ValueError, httpx2.InvalidURL) as exc:
            raise ValueError("base_url is not a valid URL") from exc
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError("base_url must be an http:// or https:// URL")
        if parts.username is not None or parts.password is not None:
            raise ValueError("base_url must not contain credentials; send them in a header")
        return url.rstrip("/")


class Targets(_Frozen):
    old: Target
    new: Target


class Suite(_Frozen):
    version: Literal[1] = 1
    targets: Targets
    # Sent with every request to both targets.
    headers: FixedHeaders = Field(default_factory=dict)
    rules: RuleSet = Field(default_factory=RuleSet)
    cases: tuple[Case, ...] = Field(min_length=1, max_length=MAX_CASES_PER_SUITE)
