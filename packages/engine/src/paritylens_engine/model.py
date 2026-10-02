"""The engine's vocabulary: responses in, differences out.

These are Pydantic models because they cross process boundaries: the CLI
writes them to a file, the API reads them back and stores them. Everything
here is immutable.
"""

import re
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, field_validator

from paritylens_engine.paths import parse_pattern

# RFC 9110 "token": the characters an HTTP header name may consist of.
_HEADER_NAME = re.compile(r"[A-Za-z0-9!#$%&'*+.^_`|~-]+")

# Each rule is tested against each difference, so their number is bounded.
MAX_RULES_PER_KIND = 200
# A step keeps at most this many differences, the most severe first.
MAX_DIFFERENCES_PER_STEP = 1000


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Severity(StrEnum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        """Position on the scale, for comparing. Declaration order is the scale."""
        return list(Severity).index(self)


class DiffKind(StrEnum):
    STATUS_CHANGED = "status_changed"
    BODY_FORMAT_CHANGED = "body_format_changed"
    HEADER_CHANGED = "header_changed"
    FIELD_ADDED = "field_added"
    FIELD_REMOVED = "field_removed"
    TYPE_CHANGED = "type_changed"
    VALUE_CHANGED = "value_changed"
    ARRAY_CHANGED = "array_changed"


class Reason(StrEnum):
    """Why a difference got the severity it has. The UI turns these into sentences."""

    DEFAULT_FOR_KIND = "default_for_kind"
    IGNORE_RULE = "ignore_rule"
    VOLATILE_IN_BASELINE = "volatile_in_baseline"
    TRACKS_REQUEST_TIME = "tracks_request_time"
    CRITICAL_RULE = "critical_rule"
    CRITICAL_FIELD_NAME = "critical_field_name"
    OUTCOME_FLIPPED = "outcome_flipped"


class NoiseSource(StrEnum):
    """What told the engine a difference is not a compatibility problem."""

    # An ignore rule the user wrote.
    RULE = "rule"
    # The value differed between two responses of the old API.
    BASELINE = "baseline"
    # The value is a timestamp of the request itself, on both sides.
    CLOCK = "clock"


class Hint(StrEnum):
    """Observations that inform a reader but never change the severity."""

    LOOKS_LIKE_UUID = "looks_like_uuid"
    LOOKS_LIKE_TIMESTAMP = "looks_like_timestamp"
    BASELINE_ALSO_DIFFERS = "baseline_also_differs"


class Note(StrEnum):
    """Things about a comparison as a whole that the reader should know."""

    BODY_NOT_COMPARED_STATUS_CLASS = "body_not_compared_status_class"
    BODY_NOT_COMPARED_TRUNCATED = "body_not_compared_truncated"
    BASELINE_UNSTABLE = "baseline_unstable"
    # The second request to the old API failed, so noise could not be detected.
    BASELINE_UNAVAILABLE = "baseline_unavailable"
    # There were more differences than a report keeps; the least severe were dropped.
    DIFFERENCES_TRUNCATED = "differences_truncated"


class Verdict(StrEnum):
    COMPATIBLE = "compatible"
    WARNING = "warning"
    BREAKING = "breaking"
    ERROR = "error"


class ResponseSnapshot(_Frozen):
    """What one API answered to one request."""

    status: int
    headers: dict[str, str] = Field(default_factory=dict)
    body: str | None = None
    body_truncated: bool = False
    duration_ms: float | None = None
    # When the response arrived. Lets the engine recognise "now" timestamps.
    received_at: AwareDatetime | None = None

    @field_validator("headers")
    @classmethod
    def _lowercase_header_names(cls, headers: dict[str, str]) -> dict[str, str]:
        # HTTP header names are case-insensitive; store one spelling.
        return {name.lower(): value for name, value in headers.items()}


class UnorderedRule(_Frozen):
    """Compare the array at `path` without regard to element order.

    With `key`, elements are paired by that field and then compared field by
    field. Without it, elements are paired only when they are entirely equal.
    """

    path: str
    key: str | None = Field(default=None, min_length=1)


class RuleSet(_Frozen):
    """Everything a user can configure about how responses are compared."""

    ignore: tuple[str, ...] = Field(default=(), max_length=MAX_RULES_PER_KIND)
    unordered: tuple[UnorderedRule, ...] = Field(default=(), max_length=MAX_RULES_PER_KIND)
    critical: tuple[str, ...] = Field(default=(), max_length=MAX_RULES_PER_KIND)
    compare_headers: tuple[str, ...] = Field(default=(), max_length=MAX_RULES_PER_KIND)
    # Treat fields named like money (total, tax_amount, ...) as critical.
    critical_field_names: bool = True
    # How far a timestamp may be from the moment of the response and still
    # count as "the time of the request". Zero turns the check off.
    clock_tolerance_seconds: int = Field(default=300, ge=0, le=3600)

    @field_validator("ignore", "critical")
    @classmethod
    def _patterns_parse(cls, patterns: tuple[str, ...]) -> tuple[str, ...]:
        for pattern in patterns:
            parse_pattern(pattern)
        return patterns

    @field_validator("unordered")
    @classmethod
    def _unordered_patterns_parse(
        cls, rules: tuple[UnorderedRule, ...]
    ) -> tuple[UnorderedRule, ...]:
        for rule in rules:
            parse_pattern(rule.path)
        return rules

    @field_validator("compare_headers")
    @classmethod
    def _header_names(cls, names: tuple[str, ...]) -> tuple[str, ...]:
        for name in names:
            if not _HEADER_NAME.fullmatch(name):
                raise ValueError("compare_headers must be HTTP header names")
        return tuple(name.lower() for name in names)


class Difference(_Frozen):
    """One way the new response differs from the old one."""

    kind: DiffKind
    # Where: "status", "header.<name>", "body", or a path such as $.items[0].price
    path: str
    # For FIELD_ADDED there is no old value, for FIELD_REMOVED no new one;
    # the kind says which, since null is also a legitimate value.
    old: JsonValue = None
    new: JsonValue = None
    detail: str | None = None
    severity: Severity
    reason: Reason
    noise_source: NoiseSource | None = None
    hints: tuple[Hint, ...] = ()


class StepComparison(_Frozen):
    """The outcome of comparing the old and new responses to one request."""

    differences: tuple[Difference, ...] = ()
    notes: tuple[Note, ...] = ()

    @property
    def max_severity(self) -> Severity:
        return max(
            (d.severity for d in self.differences), key=lambda s: s.rank, default=Severity.NONE
        )


class RunSummary(_Frozen):
    """Counts over all the cases of one run."""

    total: int
    compatible: int
    warning: int
    breaking: int
    error: int

    @property
    def evaluated(self) -> int:
        """Cases that produced a result to judge. Errors are not evidence either way."""
        return self.total - self.error

    @property
    def score(self) -> float | None:
        """Share of evaluated cases that are compatible, or None when there were none."""
        if self.evaluated == 0:
            return None
        return self.compatible / self.evaluated
