"""ParityLens comparison engine.

Pure Python, no web framework and no database. Everything that decides
whether two API responses are compatible lives here, so it can be tested
without infrastructure and shared by the CLI and the hosted worker.
"""

from paritylens_engine.compare import compare_step
from paritylens_engine.model import (
    Difference,
    DiffKind,
    Hint,
    NoiseSource,
    Note,
    Reason,
    ResponseSnapshot,
    RuleSet,
    RunSummary,
    Severity,
    StepComparison,
    UnorderedRule,
    Verdict,
)
from paritylens_engine.verdict import summarize, verdict_for

__version__ = "0.1.0"

__all__ = [
    "DiffKind",
    "Difference",
    "Hint",
    "NoiseSource",
    "Note",
    "Reason",
    "ResponseSnapshot",
    "RuleSet",
    "RunSummary",
    "Severity",
    "StepComparison",
    "UnorderedRule",
    "Verdict",
    "__version__",
    "compare_step",
    "summarize",
    "verdict_for",
]
