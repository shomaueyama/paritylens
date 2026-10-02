"""How serious is a difference?

Every rule here is deterministic: the same difference under the same rules
always gets the same severity. No model is consulted. When a rule is a
guess (a field name that sounds like money), the Reason says so, so the
reader can tell a fact from a heuristic.
"""

import re
from collections.abc import Set
from dataclasses import dataclass, field
from datetime import datetime

from paritylens_engine.clock import tracks_the_clock
from paritylens_engine.diff import RawDifference
from paritylens_engine.jsonvalue import Json, clip
from paritylens_engine.model import Difference, DiffKind, Hint, NoiseSource, Reason, Severity
from paritylens_engine.paths import Path, generalize, last_field_name
from paritylens_engine.rules import CompiledRules

_DEFAULT_SEVERITY: dict[DiffKind, Severity] = {
    DiffKind.FIELD_ADDED: Severity.LOW,
    DiffKind.HEADER_CHANGED: Severity.LOW,
    DiffKind.VALUE_CHANGED: Severity.MEDIUM,
    DiffKind.ARRAY_CHANGED: Severity.MEDIUM,
    DiffKind.FIELD_REMOVED: Severity.HIGH,
    DiffKind.TYPE_CHANGED: Severity.HIGH,
    DiffKind.BODY_FORMAT_CHANGED: Severity.HIGH,
    DiffKind.STATUS_CHANGED: Severity.HIGH,
}

# A wrong or missing value in a critical field is critical. A new field
# next to it is not.
_KINDS_THAT_CAN_BE_CRITICAL = frozenset(
    {DiffKind.VALUE_CHANGED, DiffKind.TYPE_CHANGED, DiffKind.FIELD_REMOVED}
)

_MONEY_WORDS = frozenset(
    {
        "amount",
        "balance",
        "charge",
        "cost",
        "discount",
        "fee",
        "payment",
        "price",
        "subtotal",
        "tax",
        "total",
    }
)

# Words that follow the money word without changing what the field is:
# total_jpy, amount_in_cents.
_UNIT_WORDS = frozenset({"in", "jpy", "yen", "usd", "eur", "gbp", "cent", "cents"})

# Splits snake_case, kebab-case and camelCase: "unitPrice" → unit, Price.
_WORD = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+")

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)
_TIMESTAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?", re.IGNORECASE
)


def sounds_like_money(field_name: str) -> bool:
    """True for names whose last word is a money word: total, tax_amount, unitPrice.

    Only the last word counts, after any unit: total_count and price_label
    are about a count and a label, while total_jpy is still a total.
    """
    words = [word.lower() for word in _WORD.findall(field_name)]
    while words and words[-1] in _UNIT_WORDS:
        words.pop()
    if not words:
        return False
    last = words[-1]
    if last in _MONEY_WORDS:
        return True
    # Plurals: fees, prices, taxes. Only a trailing "s" is removed, so that
    # "feed" and "taxi" are not mistaken for "fee" and "tax".
    return (last.endswith("s") and last[:-1] in _MONEY_WORDS) or (
        last.endswith("es") and last[:-2] in _MONEY_WORDS
    )


def generalized_location(raw: RawDifference) -> str:
    return generalize(raw.path) if raw.path is not None else raw.location


@dataclass(frozen=True)
class Evidence:
    """What is known about a comparison beyond the two responses themselves."""

    # Differences seen between two responses of the old API to the same
    # request, as (kind, generalized location) pairs.
    baseline: Set[tuple[DiffKind, str]] = field(default_factory=frozenset)
    # When each side answered.
    old_at: datetime | None = None
    new_at: datetime | None = None


def assess(
    raw: RawDifference, rules: CompiledRules, evidence: Evidence | None = None
) -> Difference:
    """Give a raw difference its severity."""
    evidence = evidence or Evidence()
    seen_in_baseline = (raw.kind, generalized_location(raw)) in evidence.baseline
    severity, reason, noise = _judge(raw, rules, evidence, seen_in_baseline)

    hints: list[Hint] = []
    if severity is not Severity.NONE:
        if seen_in_baseline:
            hints.append(Hint.BASELINE_ALSO_DIFFERS)
        if raw.kind is DiffKind.VALUE_CHANGED:
            hints.extend(_pattern_hints(raw))

    return Difference(
        kind=raw.kind,
        path=raw.location,
        old=clip(raw.old),
        new=clip(raw.new),
        detail=raw.detail,
        severity=severity,
        reason=reason,
        noise_source=noise,
        hints=tuple(hints),
    )


def _judge(
    raw: RawDifference, rules: CompiledRules, evidence: Evidence, seen_in_baseline: bool
) -> tuple[Severity, Reason, NoiseSource | None]:
    if raw.path is not None and rules.ignores(raw.path):
        return Severity.NONE, Reason.IGNORE_RULE, NoiseSource.RULE

    critical = _critical_reason(raw, rules)

    # The two noise tests apply to values only. If the old API always
    # returned a string in a field and the new one returns a number, that
    # is a real change no matter how much the string varied.
    #
    # They also step aside for a field the user marked critical: what a
    # person wrote outranks what the engine inferred.
    if raw.kind is DiffKind.VALUE_CHANGED and critical is not Reason.CRITICAL_RULE:
        # A value that differs between two calls to the old API changes on
        # its own, so differing from the new API proves nothing.
        if seen_in_baseline:
            return Severity.NONE, Reason.VOLATILE_IN_BASELINE, NoiseSource.BASELINE
        # An amount is never a timestamp, however much it resembles one.
        if critical is None and _is_request_time(raw, rules, evidence):
            return Severity.NONE, Reason.TRACKS_REQUEST_TIME, NoiseSource.CLOCK

    if (
        raw.kind is DiffKind.STATUS_CHANGED
        and isinstance(raw.old, int)
        and isinstance(raw.new, int)
        and (raw.old >= 400) != (raw.new >= 400)
    ):
        # One side succeeded where the other failed.
        return Severity.CRITICAL, Reason.OUTCOME_FLIPPED, None

    if critical is not None:
        return Severity.CRITICAL, critical, None
    return _DEFAULT_SEVERITY[raw.kind], Reason.DEFAULT_FOR_KIND, None


def _critical_reason(raw: RawDifference, rules: CompiledRules) -> Reason | None:
    """Whether the difference touches a critical field, and what says so."""
    if raw.path is None:
        return None
    if raw.kind in _KINDS_THAT_CAN_BE_CRITICAL:
        own = _critical_field(raw.path, rules)
        if own is not None:
            return own
    # What the old response had and the new one lacks may hold critical
    # fields further in: a removed "order" object takes its "total" with
    # it, and so does an array element that found no partner.
    if raw.kind in (DiffKind.FIELD_REMOVED, DiffKind.TYPE_CHANGED):
        return _critical_inside(raw.old, raw.path, rules)
    if raw.kind is DiffKind.ARRAY_CHANGED and isinstance(raw.old, list):
        element = (*raw.path, _ANY_POSITION)
        found = (_critical_inside(item, element, rules) for item in raw.old)
        return next((reason for reason in found if reason is not None), None)
    return None


# Stands for "some element" in a path built to test rules against.
_ANY_POSITION = -1


def _critical_field(path: Path, rules: CompiledRules) -> Reason | None:
    if rules.marks_critical(path):
        return Reason.CRITICAL_RULE
    name = last_field_name(path)
    if rules.critical_field_names and name is not None and sounds_like_money(name):
        return Reason.CRITICAL_FIELD_NAME
    return None


def _critical_inside(value: Json, path: Path, rules: CompiledRules) -> Reason | None:
    """The first critical field found in a value, searching depth first."""
    if isinstance(value, dict):
        for name, item in value.items():
            child = (*path, name)
            reason = _critical_field(child, rules) or _critical_inside(item, child, rules)
            if reason is not None:
                return reason
    elif isinstance(value, list):
        for item in value:
            reason = _critical_inside(item, (*path, _ANY_POSITION), rules)
            if reason is not None:
                return reason
    return None


def _is_request_time(raw: RawDifference, rules: CompiledRules, evidence: Evidence) -> bool:
    if evidence.old_at is None or evidence.new_at is None or not rules.clock_tolerance:
        return False
    return tracks_the_clock(
        raw.old,
        raw.new,
        old_at=evidence.old_at,
        new_at=evidence.new_at,
        tolerance=rules.clock_tolerance,
    )


def _pattern_hints(raw: RawDifference) -> list[Hint]:
    """Values shaped like an ID or a time are worth pointing out, never worth hiding."""
    if not (isinstance(raw.old, str) and isinstance(raw.new, str)):
        return []
    if _UUID.fullmatch(raw.old) and _UUID.fullmatch(raw.new):
        return [Hint.LOOKS_LIKE_UUID]
    if _TIMESTAMP.fullmatch(raw.old) and _TIMESTAMP.fullmatch(raw.new):
        return [Hint.LOOKS_LIKE_TIMESTAMP]
    return []
