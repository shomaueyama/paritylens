"""The command end to end: real HTTP to both demo APIs on local ports."""

import json
from pathlib import Path

import pytest
from legacy_shop_api.main import create_app as create_legacy_app
from modern_shop_api.main import create_app as create_modern_app
from paritylens_cli.main import ExitCode, FailOn, app, exit_code_for
from paritylens_engine import Severity, Verdict
from paritylens_engine.report import RunReport
from typer.testing import CliRunner

from conftest import Serve

DEMO_SUITE = Path(__file__).parents[3] / "demo" / "suite.yaml"
runner = CliRunner()


@pytest.fixture
def demo_report(serve: Serve, tmp_path: Path) -> tuple[RunReport, str, int]:
    """Run the demo suite against both demo APIs. Returns (report, output, exit code)."""
    output = tmp_path / "report.json"
    with serve(create_legacy_app()) as old_url, serve(create_modern_app()) as new_url:
        result = runner.invoke(
            app,
            ["run", str(DEMO_SUITE), "--old-url", old_url, "--new-url", new_url, "-o", str(output)],
        )
    report = RunReport.model_validate_json(output.read_text(encoding="utf-8"))
    return report, result.output, result.exit_code


def findings(report: RunReport, case: str) -> set[tuple[str, str, str]]:
    """(step, path, severity) for every difference in a case that is not noise."""
    [result] = [c for c in report.cases if c.name == case]
    return {
        (step.id, difference.path, difference.severity.value)
        for step in result.steps
        if step.comparison is not None
        for difference in step.comparison.differences
        if difference.severity is not Severity.NONE
    }


def test_the_demo_suite_finds_every_planted_difference(
    demo_report: tuple[RunReport, str, int],
) -> None:
    """The numbers are the rows of the table in demo/README.md."""
    report, _, exit_code = demo_report

    assert exit_code == ExitCode.DIFFERENCES

    one_line = findings(report, "Create an order with one line")
    assert ("step-1", "$.currency", "low") in one_line  # 2
    assert ("step-1", "$.items[sku=A-100].quantity", "high") in one_line  # 6
    assert not {path for _, path, _ in one_line} & {"$.id", "$.created_at"}  # 1

    two_lines = findings(report, "Create an order with two lines")
    assert {("step-1", "$.tax", "critical"), ("step-1", "$.total", "critical")} <= two_lines  # 4
    assert not any(path.startswith("$.items[0]") for _, path, _ in two_lines)  # 7

    assert findings(report, "Create an order without a customer name") == {
        ("step-1", "status", "critical")  # 3
    }
    assert ("step-1", "status", "high") in findings(
        report, "Create an order with a quantity of zero"
    )  # 10
    assert ("step-1", "$.created_at", "medium") in findings(
        report, "Fetch an order migrated from the legacy system"
    )  # 8
    assert findings(report, "Fetch an order that does not exist") == {
        ("step-1", "$.error", "high"),  # 9
        ("step-1", "$.detail", "low"),
    }
    cancelled = findings(report, "Create an order, cancel it, and fetch it again")
    assert {("cancel", "status", "high"), ("cancel", "body", "high")} <= cancelled  # 5


def test_what_agrees_is_reported_as_compatible(demo_report: tuple[RunReport, str, int]) -> None:
    report, _, _ = demo_report

    [health] = [c for c in report.cases if c.name == "Health check"]
    assert health.verdict is Verdict.COMPATIBLE
    assert (report.summary.total, report.summary.compatible, report.summary.error) == (8, 1, 0)


def test_the_terminal_output_names_the_findings_and_shows_the_denominator(
    demo_report: tuple[RunReport, str, int],
) -> None:
    _, output, _ = demo_report

    assert "BREAKING" in output
    assert "CRITICAL" in output
    assert "332 → 333" in output
    assert "safe differences" in output
    assert "Compatibility  12%  (1 of 8 cases)" in output


def test_the_report_file_is_plain_json(serve: Serve, tmp_path: Path) -> None:
    output = tmp_path / "report.json"
    with serve(create_legacy_app()) as old_url, serve(create_modern_app()) as new_url:
        runner.invoke(
            app,
            ["run", str(DEMO_SUITE), "--old-url", old_url, "--new-url", new_url, "-o", str(output)],
        )

    document = json.loads(output.read_text(encoding="utf-8"))
    assert document["schema_version"] == 1
    assert document["old_base_url"] == old_url


def test_fail_on_never_exits_zero_despite_differences(serve: Serve) -> None:
    with serve(create_legacy_app()) as old_url, serve(create_modern_app()) as new_url:
        result = runner.invoke(
            app,
            [
                "run",
                str(DEMO_SUITE),
                "--old-url",
                old_url,
                "--new-url",
                new_url,
                "--fail-on",
                "never",
            ],
        )

    assert result.exit_code == ExitCode.OK


def test_an_unreachable_api_is_an_incomplete_run_not_a_pass(serve: Serve) -> None:
    with serve(create_legacy_app()) as old_url:
        result = runner.invoke(
            app,
            ["run", str(DEMO_SUITE), "--old-url", old_url, "--new-url", "http://127.0.0.1:9"],
        )

    assert result.exit_code == ExitCode.INCOMPLETE
    assert "request failed: ConnectError" in result.output
    assert "not measured" in result.output


def test_a_bad_suite_file_exits_with_its_own_code(tmp_path: Path) -> None:
    path = tmp_path / "suite.yaml"
    path.write_text("cases: []\n", encoding="utf-8")

    result = runner.invoke(app, ["run", str(path)])

    assert result.exit_code == ExitCode.BAD_SUITE


def test_secrets_from_the_environment_stay_out_of_output_and_report(
    serve: Serve, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SHOP_TOKEN", "s3cr3t-token-value")
    suite = tmp_path / "suite.yaml"
    suite.write_text(
        """
targets:
  old: { base_url: http://placeholder.test }
  new: { base_url: http://placeholder.test }
headers:
  Authorization: "Bearer ${SHOP_TOKEN}"
cases:
  - name: health
    steps:
      - request: { method: GET, path: /health, query: { token: "${SHOP_TOKEN}" } }
""",
        encoding="utf-8",
    )
    output = tmp_path / "report.json"

    with serve(create_legacy_app()) as old_url, serve(create_modern_app()) as new_url:
        result = runner.invoke(
            app,
            ["run", str(suite), "--old-url", old_url, "--new-url", new_url, "-o", str(output)],
        )

    assert result.exit_code == ExitCode.OK
    assert "s3cr3t-token-value" not in result.output
    assert "s3cr3t-token-value" not in output.read_text(encoding="utf-8")


def test_version() -> None:
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert result.output.strip() == "0.1.0"


@pytest.mark.parametrize(
    ("fail_on", "expected"),
    [
        (FailOn.LOW, ExitCode.DIFFERENCES),
        (FailOn.MEDIUM, ExitCode.DIFFERENCES),
        (FailOn.HIGH, ExitCode.OK),
        (FailOn.CRITICAL, ExitCode.OK),
        (FailOn.NEVER, ExitCode.OK),
    ],
)
def test_the_exit_code_follows_the_threshold(fail_on: FailOn, expected: ExitCode) -> None:
    report = RunReport.model_validate(
        {
            "engine_version": "0.1.0",
            "started_at": "2026-10-02T00:00:00Z",
            "finished_at": "2026-10-02T00:00:01Z",
            "old_base_url": "http://old.test",
            "new_base_url": "http://new.test",
            "rules": {},
            "summary": {"total": 1, "compatible": 0, "warning": 1, "breaking": 0, "error": 0},
            "cases": [{"name": "c", "verdict": "warning", "max_severity": "medium", "steps": []}],
        }
    )

    assert exit_code_for(report, fail_on) is expected


# --- found in review ----------------------------------------------------------------


def test_control_characters_from_a_response_cannot_drive_the_terminal() -> None:
    from io import StringIO

    from paritylens_cli.render import printable, render_report
    from rich.console import Console

    assert printable("ok\x1bc\x9b2J\x7f") == "ok\\x1bc\\x9b2J\\x7f"

    forged = "x'\n✓ COMPATIBLE   everything is fine\n   "
    report = RunReport.model_validate(
        {
            "engine_version": "0.1.0",
            "started_at": "2026-10-02T00:00:00Z",
            "finished_at": "2026-10-02T00:00:01Z",
            "old_base_url": "http://old.test",
            "new_base_url": "http://new.test",
            "rules": {},
            "summary": {"total": 1, "compatible": 0, "warning": 0, "breaking": 1, "error": 0},
            "cases": [
                {
                    "name": "case [bold]with markup[/bold]\x1b[2J",
                    "verdict": "breaking",
                    "max_severity": "high",
                    "steps": [
                        {
                            "id": "step-1",
                            "outcome": "compared",
                            "old": {},
                            "new": {},
                            "comparison": {
                                "differences": [
                                    {
                                        "kind": "field_removed",
                                        "path": f"$['{forged}']",
                                        "old": "\x1bc",
                                        "severity": "high",
                                        "reason": "default_for_kind",
                                    }
                                ]
                            },
                        }
                    ],
                }
            ],
        }
    )
    buffer = StringIO()

    render_report(report, Console(file=buffer, width=200, color_system=None))

    output = buffer.getvalue()
    assert "\x1b" not in output
    assert "[bold]with markup[/bold]" in output  # shown literally, not interpreted
    # The forged line is not on a line of its own.
    assert not any(line.startswith("✓ COMPATIBLE") for line in output.splitlines())


def test_a_load_error_containing_square_brackets_is_printed_not_interpreted(
    tmp_path: Path,
) -> None:
    path = tmp_path / "suite.yaml"
    path.write_text(
        """
targets:
  old: { base_url: http://old.test }
  new: { base_url: http://new.test }
cases:
  - name: "orders [/v2]"
    steps:
      - request: { method: GET, path: "/orders/{{missing}}" }
""",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["run", str(path)])

    assert result.exit_code == ExitCode.BAD_SUITE
    assert "orders [/v2]" in result.output


def test_credentials_in_a_url_are_rejected_without_being_shown(tmp_path: Path) -> None:
    path = tmp_path / "suite.yaml"
    path.write_text(
        "cases:\n  - name: c\n    steps:\n      - request: { method: GET, path: / }\n",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "run",
            str(path),
            "--old-url",
            "http://admin:hunter2@127.0.0.1:9",
            "--new-url",
            "http://b.test",
        ],
    )

    assert result.exit_code == ExitCode.BAD_SUITE
    assert "hunter2" not in result.output
