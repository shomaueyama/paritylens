"""Recognising values that are "the time of the request".

Calling the old API twice exposes most volatile values, but not a
timestamp with one-second resolution when both calls land in the same
second, which is the usual case. Those would be reported as differences
on every run.

So there is a second, independent test: a value is clock-driven when, on
each side, it is a timestamp close to the moment that side answered. A
stored timestamp (an order placed in January) is not close to now on either
side, so it is not affected and stays comparable.
"""

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from paritylens_engine.jsonvalue import Json

# A timestamp without an offset is local time somewhere. Offsets in use run
# from UTC-12 to UTC+14 in steps of a quarter of an hour.
_OFFSET_STEP = timedelta(minutes=15)
_MIN_OFFSET = timedelta(hours=-12)
_MAX_OFFSET = timedelta(hours=14)

# Shortest text that carries a time of day: 2026-01-15T10:00
_MIN_LENGTH_WITH_TIME = 16

# Unix time has ten digits in seconds and thirteen in milliseconds. A number
# with a far larger magnitude is not a timestamp, and arithmetic on it could
# overflow.
_MAX_EPOCH_DIGITS = 15


@dataclass(frozen=True)
class _Reading:
    """A value read as a timestamp: how it states the time, and how far it
    is from the moment its response arrived."""

    # "instant": text with an offset. "local": text without one.
    # "epoch seconds" / "epoch milliseconds": a Unix time number.
    form: str
    distance: timedelta


def tracks_the_clock(
    old: Json, new: Json, *, old_at: datetime, new_at: datetime, tolerance: timedelta
) -> bool:
    """True when both values are timestamps taken at their own side's request time."""
    old_reading = _read(old, old_at)
    new_reading = _read(new, new_at)
    if old_reading is None or new_reading is None:
        return False
    # Both must state the time the same way. If one side writes an offset
    # and the other does not, or one counts seconds and the other
    # milliseconds, clients see a different value: a real difference.
    if old_reading.form != new_reading.form:
        return False
    if old_reading.form != "local":
        return abs(old_reading.distance) <= tolerance and abs(new_reading.distance) <= tolerance
    return _same_local_now(old_reading.distance, new_reading.distance, tolerance)


def _same_local_now(old: timedelta, new: timedelta, tolerance: timedelta) -> bool:
    """Whether two offset-less times are both "now" in one and the same timezone.

    Without an offset the zone has to be inferred: there must be a single
    UTC offset under which both values are within tolerance of now. Local
    time in Tokyo on one side and UTC on the other fails this, as it
    should, since clients would see values nine hours apart.
    """
    first = math.ceil((old - tolerance) / _OFFSET_STEP)
    last = math.floor((old + tolerance) / _OFFSET_STEP)
    for step in range(first, last + 1):
        offset = step * _OFFSET_STEP
        if _MIN_OFFSET <= offset <= _MAX_OFFSET and abs(new - offset) <= tolerance:
            return True
    return False


def _read(value: Json, at: datetime) -> _Reading | None:
    """Read the value as a timestamp, or None if it is not one."""
    try:
        if isinstance(value, str):
            return _read_text(value, at)
        if isinstance(value, bool):
            return None
        if isinstance(value, int | Decimal):
            return _read_epoch(Decimal(value), at)
    except ArithmeticError:
        # Dates at the edge of what datetime can represent overflow.
        return None
    return None


def _read_text(text: str, at: datetime) -> _Reading | None:
    if len(text) < _MIN_LENGTH_WITH_TIME:
        return None  # a date alone does not change within a run
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return _Reading("instant", parsed - at)
    return _Reading("local", parsed - at.astimezone(UTC).replace(tzinfo=None))


def _read_epoch(number: Decimal, at: datetime) -> _Reading | None:
    """Unix time, in seconds or milliseconds. The unit is part of the reading:
    a field that switched from seconds to milliseconds did change."""
    if not number.is_finite() or number.adjusted() > _MAX_EPOCH_DIGITS:
        return None
    now = Decimal(at.timestamp())
    in_seconds = number - now
    in_milliseconds = number / 1000 - now
    if abs(in_seconds) <= abs(in_milliseconds):
        return _Reading("epoch seconds", timedelta(seconds=float(in_seconds)))
    return _Reading("epoch milliseconds", timedelta(seconds=float(in_milliseconds)))
