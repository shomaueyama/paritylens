"""The engine's front door: compare two responses to the same request."""

from paritylens_engine.diff import diff_responses
from paritylens_engine.model import (
    MAX_DIFFERENCES_PER_STEP,
    Difference,
    DiffKind,
    Note,
    ResponseSnapshot,
    RuleSet,
    StepComparison,
)
from paritylens_engine.rules import compile_rules
from paritylens_engine.severity import Evidence, assess, generalized_location


def compare_step(
    old: ResponseSnapshot,
    new: ResponseSnapshot,
    *,
    rules: RuleSet | None = None,
    baseline: ResponseSnapshot | None = None,
) -> StepComparison:
    """Compare the new API's response against the old API's.

    `baseline` is a second response from the *old* API to the same request.
    Whatever differs between `old` and `baseline` changes from call to call
    (IDs, tokens), so the same value differing in `new` is not counted
    against it.

    When both responses carry `received_at`, timestamps that match the
    moment of their own response are recognised as the request time and
    not counted either.

    This function is pure: no network, no clock, no randomness. Given the
    same arguments it returns the same result.
    """
    compiled = compile_rules(rules or RuleSet())
    raw_differences, notes = diff_responses(old, new, compiled)

    seen_in_baseline: set[tuple[DiffKind, str]] = set()
    if baseline is not None:
        baseline_differences, _ = diff_responses(old, baseline, compiled)
        seen_in_baseline = {(raw.kind, generalized_location(raw)) for raw in baseline_differences}
        # If the old API cannot agree with itself on the status, there is
        # no stable behaviour to hold the new API to.
        if any(raw.kind is DiffKind.STATUS_CHANGED for raw in baseline_differences):
            notes.append(Note.BASELINE_UNSTABLE)

    evidence = Evidence(
        baseline=frozenset(seen_in_baseline), old_at=old.received_at, new_at=new.received_at
    )
    differences = [assess(raw, compiled, evidence) for raw in raw_differences]
    if len(differences) > MAX_DIFFERENCES_PER_STEP:
        differences = _most_severe(differences, MAX_DIFFERENCES_PER_STEP)
        notes.append(Note.DIFFERENCES_TRUNCATED)
    return StepComparison(differences=tuple(differences), notes=tuple(notes))


def _most_severe(differences: list[Difference], limit: int) -> list[Difference]:
    """Keep the `limit` most severe differences, in their original order.

    A response with tens of thousands of differing fields would otherwise
    produce a report too large to store or read. What is dropped is the
    least severe, so the verdict is unaffected.
    """
    by_severity = sorted(range(len(differences)), key=lambda i: -differences[i].severity.rank)
    kept = sorted(by_severity[:limit])
    return [differences[i] for i in kept]
