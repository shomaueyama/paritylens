"""Recognising timestamps that are simply "when the request happened"."""

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from paritylens_engine import (
    NoiseSource,
    Reason,
    ResponseSnapshot,
    RuleSet,
    Severity,
    compare_step,
)
from paritylens_engine.clock import tracks_the_clock
from pydantic import ValidationError

# The old API answered at 01:00:00 UTC, the new one two seconds later.
OLD_AT = datetime(2026, 10, 2, 1, 0, 0, tzinfo=UTC)
NEW_AT = OLD_AT + timedelta(seconds=2)
FIVE_MINUTES = timedelta(minutes=5)


def clock_driven(old: Any, new: Any) -> bool:
    return tracks_the_clock(old, new, old_at=OLD_AT, new_at=NEW_AT, tolerance=FIVE_MINUTES)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        # Same instant, written with different offsets and precision.
        ("2026-10-02T10:00:00+09:00", "2026-10-02T01:00:02.542478Z"),
        ("2026-10-02T01:00:00Z", "2026-10-02T01:00:02Z"),
        ("2026-10-02 01:00:00+00:00", "2026-10-02T01:00:02+00:00"),
        # Servers whose clocks are a minute or two off.
        ("2026-10-02T00:58:10Z", "2026-10-02T01:03:00Z"),
        # Unix time, in seconds or in milliseconds.
        (1790902800, 1790902802),
        (1790902800123, 1790902802456),
        # Local time without an offset, the same zone on both sides.
        ("2026-10-02T10:00:00", "2026-10-02 10:00:02"),
        ("2026-10-02T01:00:00", "2026-10-02T01:00:02"),
    ],
)
def test_timestamps_of_the_request_itself_are_clock_driven(old: Any, new: Any) -> None:
    assert clock_driven(old, new)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        # A stored timestamp that differs: the migration bug in the demo.
        ("2026-01-15T10:00:00+09:00", "2026-01-15T10:00:00Z"),
        # Only one side is "now".
        ("2026-10-02T01:00:00Z", "2026-10-01T01:00:00Z"),
        # Both now, but the new API is nine hours off (JST labelled as UTC).
        ("2026-10-02T10:00:00+09:00", "2026-10-02T10:00:02Z"),
        # Local time on both sides, but in different zones: clients see 9h.
        ("2026-10-02T10:00:00", "2026-10-02T01:00:02"),
        # One written with an offset, one without: not the same contract.
        ("2026-10-02T01:00:00Z", "2026-10-02T01:00:02"),
        # A date alone is not a clock reading.
        ("2026-10-02", "2026-10-03"),
        # Not timestamps.
        ("ORD-000002", "53e59e2f-26e5-4e78-a913-6c6cb26f3527"),
        (100, 101),
        (True, False),
        (None, "2026-10-02T01:00:02Z"),
        ("2026-10-02T01:00:00Z", 1790902802),
        # Unix time that switched from seconds to milliseconds.
        (1790902800, 1790902802123),
    ],
)
def test_other_values_are_not(old: Any, new: Any) -> None:
    assert not clock_driven(old, new)


def response(created_at: str, at: datetime | None) -> ResponseSnapshot:
    return ResponseSnapshot(
        status=200,
        headers={"content-type": "application/json"},
        body=f'{{"created_at": "{created_at}"}}',
        received_at=at,
    )


def test_a_request_time_timestamp_is_noise_even_when_the_baseline_missed_it() -> None:
    """Two calls within one second return the same one-second timestamp."""
    old = response("2026-10-02T10:00:00+09:00", OLD_AT)
    same_second = response("2026-10-02T10:00:00+09:00", OLD_AT)
    new = response("2026-10-02T01:00:02.542478Z", NEW_AT)

    [difference] = compare_step(old, new, baseline=same_second).differences

    assert (difference.severity, difference.reason, difference.noise_source) == (
        Severity.NONE,
        Reason.TRACKS_REQUEST_TIME,
        NoiseSource.CLOCK,
    )


def test_a_stored_timestamp_is_still_a_real_difference() -> None:
    old = response("2026-01-15T10:00:00+09:00", OLD_AT)
    new = response("2026-01-15T10:00:00Z", NEW_AT)

    [difference] = compare_step(old, new, baseline=old).differences

    assert difference.severity is Severity.MEDIUM
    assert difference.noise_source is None


def test_without_arrival_times_the_check_does_not_apply() -> None:
    old = response("2026-10-02T10:00:00+09:00", None)
    new = response("2026-10-02T01:00:02Z", None)

    [difference] = compare_step(old, new).differences

    assert difference.severity is Severity.MEDIUM


def test_the_check_can_be_turned_off() -> None:
    old = response("2026-10-02T10:00:00+09:00", OLD_AT)
    new = response("2026-10-02T01:00:02Z", NEW_AT)

    [difference] = compare_step(old, new, rules=RuleSet(clock_tolerance_seconds=0)).differences

    assert difference.severity is Severity.MEDIUM


def test_arrival_times_must_carry_a_timezone() -> None:
    """A naive datetime here would make every comparison depend on the machine's zone."""
    with pytest.raises(ValidationError):
        ResponseSnapshot(status=200, received_at=datetime(2026, 10, 2, 1, 0, 0))


# --- found in review ----------------------------------------------------------


def test_local_times_work_with_a_tolerance_wider_than_the_offset_grid() -> None:
    """Rounding to a 15-minute offset first split these two into different zones."""
    assert tracks_the_clock(
        "2026-10-02T01:07:29",
        "2026-10-02T01:07:31",
        old_at=OLD_AT,
        new_at=OLD_AT,
        tolerance=timedelta(minutes=10),
    )


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (Decimal("1E+1000000"), Decimal("2E+1000000")),
        (1, Decimal("1E+1000000")),
        (10**400, 10**400 + 1),
        (-1790902800, 1790902800),
    ],
)
def test_numbers_far_outside_unix_time_are_not_timestamps_and_do_not_overflow(
    old: Any, new: Any
) -> None:
    assert not clock_driven(old, new)


def test_arrival_times_at_the_edge_of_the_calendar_do_not_overflow() -> None:
    at = datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=14)))

    assert not tracks_the_clock(
        "2026-10-02T01:00:00",
        "2026-10-02T01:00:01",
        old_at=at,
        new_at=at,
        tolerance=FIVE_MINUTES,
    )


def test_an_amount_that_happens_to_look_like_unix_time_is_not_noise() -> None:
    old = ResponseSnapshot(status=200, body='{"balance": 1790902800}', received_at=OLD_AT)
    new = ResponseSnapshot(status=200, body='{"balance": 1790902900}', received_at=NEW_AT)

    [difference] = compare_step(old, new).differences

    assert difference.severity is Severity.CRITICAL
