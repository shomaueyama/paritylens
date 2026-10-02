import pytest
from paritylens_engine import Severity, Verdict, summarize, verdict_for


@pytest.mark.parametrize(
    ("severity", "verdict"),
    [
        (Severity.NONE, Verdict.COMPATIBLE),
        (Severity.LOW, Verdict.COMPATIBLE),
        (Severity.MEDIUM, Verdict.WARNING),
        (Severity.HIGH, Verdict.BREAKING),
        (Severity.CRITICAL, Verdict.BREAKING),
    ],
)
def test_verdict_for(severity: Severity, verdict: Verdict) -> None:
    assert verdict_for(severity) is verdict


def test_summary_counts_each_verdict() -> None:
    summary = summarize(
        [Verdict.COMPATIBLE] * 47 + [Verdict.WARNING] + [Verdict.BREAKING] * 2 + [Verdict.ERROR] * 3
    )

    assert (
        summary.total,
        summary.compatible,
        summary.warning,
        summary.breaking,
        summary.error,
    ) == (
        53,
        47,
        1,
        2,
        3,
    )


def test_the_score_is_the_share_of_evaluated_cases_that_are_compatible() -> None:
    summary = summarize([Verdict.COMPATIBLE] * 47 + [Verdict.WARNING] + [Verdict.BREAKING] * 2)

    assert summary.evaluated == 50
    assert summary.score == pytest.approx(0.94)


def test_errors_do_not_count_for_or_against_the_score() -> None:
    """A case that could not run says nothing about compatibility."""
    summary = summarize([Verdict.COMPATIBLE, Verdict.ERROR, Verdict.ERROR])

    assert summary.evaluated == 1
    assert summary.score == 1.0


@pytest.mark.parametrize("verdicts", [[], [Verdict.ERROR, Verdict.ERROR]])
def test_no_score_when_nothing_was_evaluated(verdicts: list[Verdict]) -> None:
    """Not 0% and not 100%: there is no evidence either way."""
    assert summarize(verdicts).score is None
