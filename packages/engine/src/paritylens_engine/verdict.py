"""Roll differences up into a verdict per case and a score per run."""

from collections import Counter
from collections.abc import Iterable

from paritylens_engine.model import RunSummary, Severity, Verdict


def verdict_for(max_severity: Severity) -> Verdict:
    """The verdict of a case whose worst difference has this severity."""
    if max_severity.rank >= Severity.HIGH.rank:
        return Verdict.BREAKING
    if max_severity is Severity.MEDIUM:
        return Verdict.WARNING
    return Verdict.COMPATIBLE


def summarize(verdicts: Iterable[Verdict]) -> RunSummary:
    counts = Counter(verdicts)
    return RunSummary(
        total=sum(counts.values()),
        compatible=counts[Verdict.COMPATIBLE],
        warning=counts[Verdict.WARNING],
        breaking=counts[Verdict.BREAKING],
        error=counts[Verdict.ERROR],
    )
