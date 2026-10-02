from pathlib import Path

import pytest
from paritylens_cli.loader import SuiteLoadError, load_suite

MINIMAL = """
targets:
  old: { base_url: http://old.test }
  new: { base_url: http://new.test }
cases:
  - name: list orders
    steps:
      - request: { method: GET, path: /orders }
"""


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "suite.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_a_minimal_suite_loads(tmp_path: Path) -> None:
    loaded = load_suite(write(tmp_path, MINIMAL), env={})

    assert loaded.suite.cases[0].name == "list orders"
    assert loaded.secrets == frozenset()


def test_environment_references_are_filled_in_and_remembered_as_secrets(tmp_path: Path) -> None:
    text = MINIMAL + 'headers:\n  Authorization: "Bearer ${SHOP_TOKEN}"\n  X-Tenant: ${TENANT}\n'

    loaded = load_suite(write(tmp_path, text), env={"SHOP_TOKEN": "abc123", "TENANT": "acme"})

    assert loaded.suite.headers == {"Authorization": "Bearer abc123", "X-Tenant": "acme"}
    assert loaded.secrets == {"abc123", "acme"}


def test_every_missing_environment_variable_is_named(tmp_path: Path) -> None:
    text = MINIMAL + "headers:\n  A: ${FIRST}\n  B: ${SECOND}\n"

    with pytest.raises(SuiteLoadError, match="environment variables not set: FIRST, SECOND"):
        load_suite(write(tmp_path, text), env={})


def test_request_placeholders_are_not_environment_references(tmp_path: Path) -> None:
    """{{name}} is filled in at run time from a response, not from the environment."""
    text = """
targets:
  old: { base_url: http://old.test }
  new: { base_url: http://new.test }
cases:
  - name: create then fetch
    steps:
      - request: { method: POST, path: /orders }
        capture: { order_id: $.id }
      - request: { method: GET, path: "/orders/{{order_id}}" }
"""

    loaded = load_suite(write(tmp_path, text), env={})

    assert loaded.suite.cases[0].steps[1].request.path == "/orders/{{order_id}}"


def test_urls_can_be_overridden_from_the_command_line(tmp_path: Path) -> None:
    loaded = load_suite(
        write(tmp_path, MINIMAL), env={}, old_url="http://localhost:8001", new_url=None
    )

    assert loaded.suite.targets.old.base_url == "http://localhost:8001"
    assert loaded.suite.targets.new.base_url == "http://new.test"


def test_targets_may_come_entirely_from_the_command_line(tmp_path: Path) -> None:
    text = "cases:\n  - name: c\n    steps:\n      - request: { method: GET, path: / }\n"

    loaded = load_suite(
        write(tmp_path, text), env={}, old_url="http://a.test", new_url="http://b.test"
    )

    assert loaded.suite.targets.new.base_url == "http://b.test"


def test_a_missing_file_is_reported_plainly(tmp_path: Path) -> None:
    with pytest.raises(SuiteLoadError, match="cannot read"):
        load_suite(tmp_path / "nope.yaml", env={})


@pytest.mark.parametrize("text", ["targets: [unclosed", "- just\n- a list\n", "", "42"])
def test_files_that_are_not_a_yaml_mapping_are_rejected(tmp_path: Path, text: str) -> None:
    with pytest.raises(SuiteLoadError):
        load_suite(write(tmp_path, text), env={})


def test_validation_errors_say_where_the_problem_is(tmp_path: Path) -> None:
    text = MINIMAL.replace("method: GET", "method: FETCH")

    with pytest.raises(SuiteLoadError) as raised:
        load_suite(write(tmp_path, text), env={})

    message = str(raised.value)
    assert "is not a valid suite" in message
    assert "cases.0.steps.0.request.method" in message


def test_yaml_cannot_construct_python_objects(tmp_path: Path) -> None:
    """safe_load: a suite file from someone else must not be able to run code."""
    text = "targets: !!python/object/apply:os.system ['echo unsafe']\n"

    with pytest.raises(SuiteLoadError, match="not valid YAML"):
        load_suite(write(tmp_path, text), env={})


# --- found in review ----------------------------------------------------------------


def test_an_environment_value_that_looks_like_a_placeholder_is_refused(tmp_path: Path) -> None:
    text = MINIMAL + 'headers:\n  Authorization: "Bearer ${TOKEN}"\n'

    with pytest.raises(SuiteLoadError) as raised:
        load_suite(write(tmp_path, text), env={"TOKEN": "abc{{hunter2}}xyz"})

    assert "TOKEN" in str(raised.value)
    assert "hunter2" not in str(raised.value)


def test_a_validation_error_does_not_repeat_a_value_from_the_environment(tmp_path: Path) -> None:
    text = MINIMAL + "rules:\n  ignore: ['$[${TOKEN}']\n"

    with pytest.raises(SuiteLoadError) as raised:
        load_suite(write(tmp_path, text), env={"TOKEN": "s3cr3t-value"})

    assert "s3cr3t-value" not in str(raised.value)


def test_a_file_that_is_not_utf8_is_reported_plainly(tmp_path: Path) -> None:
    path = tmp_path / "suite.yaml"
    path.write_bytes("name: caf\xe9".encode("latin-1"))

    with pytest.raises(SuiteLoadError, match="not UTF-8"):
        load_suite(path, env={})


def test_yaml_anchors_cannot_blow_up_the_loader(tmp_path: Path) -> None:
    lines = ["a0: &a0 [x, x, x, x, x, x, x, x, x, x]"]
    lines += [f"a{n}: &a{n} [{', '.join([f'*a{n - 1}'] * 10)}]" for n in range(1, 9)]

    with pytest.raises(SuiteLoadError, match="too large"):
        load_suite(write(tmp_path, "\n".join(lines) + "\n"), env={})
