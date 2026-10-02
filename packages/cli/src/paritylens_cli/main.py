"""The paritylens command."""

import asyncio
from enum import IntEnum, StrEnum
from pathlib import Path
from typing import Annotated

import typer
from paritylens_engine import Severity, __version__
from paritylens_engine.egress import EgressMode, EgressPolicy
from paritylens_engine.executor import Executor, ExecutorSettings
from paritylens_engine.redact import Redactor
from paritylens_engine.report import RunReport
from rich.console import Console

from paritylens_cli.loader import SuiteLoadError, load_suite
from paritylens_cli.render import printable, render_report

app = typer.Typer(
    help="Check that a rewritten API still behaves like the one it replaces.",
    no_args_is_help=True,
    add_completion=False,
)


class ExitCode(IntEnum):
    OK = 0
    # Differences at or above the --fail-on severity were found.
    DIFFERENCES = 1
    # The suite file could not be loaded.
    BAD_SUITE = 2
    # No such differences, but some cases could not be run at all.
    INCOMPLETE = 3


class FailOn(StrEnum):
    """The lowest severity that makes the command fail. "never" only fails on errors."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    NEVER = "never"


@app.callback()
def main() -> None:
    """Check that a rewritten API still behaves like the one it replaces."""


@app.command()
def version() -> None:
    """Print the version."""
    typer.echo(__version__)


@app.command()
def run(
    suite_file: Annotated[Path, typer.Argument(help="The suite to run (YAML).")],
    old_url: Annotated[
        str | None, typer.Option(help="Base URL of the old API, overriding the suite file.")
    ] = None,
    new_url: Annotated[
        str | None, typer.Option(help="Base URL of the new API, overriding the suite file.")
    ] = None,
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Write the full report here as JSON.")
    ] = None,
    fail_on: Annotated[
        FailOn, typer.Option(help="Exit with status 1 if a difference is at least this severe.")
    ] = FailOn.HIGH,
    concurrency: Annotated[
        int, typer.Option(min=1, max=32, help="How many cases to run at once.")
    ] = 4,
) -> None:
    """Send every request in SUITE_FILE to both APIs and report how the answers differ."""
    console = Console()
    try:
        loaded = load_suite(suite_file, old_url=old_url, new_url=new_url)
    except SuiteLoadError as exc:
        # markup=False: the message quotes the file, which may contain "[...]".
        Console(stderr=True).print(printable(str(exc)), style="red", markup=False, highlight=False)
        raise typer.Exit(ExitCode.BAD_SUITE) from exc

    # The CLI runs on the user's own machine against APIs they can already
    # reach, so private addresses are allowed. Metadata endpoints are not.
    executor = Executor(
        policy=EgressPolicy(mode=EgressMode.PERMISSIVE),
        settings=ExecutorSettings(concurrency=concurrency),
        redactor=Redactor(loaded.secrets),
    )
    report = asyncio.run(executor.run(loaded.suite))

    render_report(report, console)
    if output is not None:
        output.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        console.print(f"\nreport written to {output}")

    raise typer.Exit(exit_code_for(report, fail_on))


def exit_code_for(report: RunReport, fail_on: FailOn) -> ExitCode:
    if fail_on is not FailOn.NEVER:
        threshold = Severity(fail_on.value).rank
        if any(case.max_severity.rank >= threshold for case in report.cases):
            return ExitCode.DIFFERENCES
    if report.summary.error:
        return ExitCode.INCOMPLETE
    return ExitCode.OK
