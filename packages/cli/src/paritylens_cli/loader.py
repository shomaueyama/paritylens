"""Reading a suite file.

Suite files are YAML and get committed to a repository, so they must not
contain credentials. A value written as ${NAME} is filled in from the
environment when the file is loaded, and remembered as a secret so that it
can be kept out of the report.
"""

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from paritylens_engine.redact import Redactor
from paritylens_engine.suite import Suite
from pydantic import ValidationError

_ENV_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

MAX_SUITE_BYTES = 1024 * 1024
# YAML anchors let a few lines describe an enormous structure. A suite has
# no use for one, so loading stops well before memory becomes a concern.
MAX_SUITE_NODES = 100_000


class SuiteLoadError(Exception):
    """The suite file could not be turned into a Suite. The message is for the user."""


@dataclass(frozen=True)
class LoadedSuite:
    suite: Suite
    # Values that came from the environment and must not be printed or stored.
    secrets: frozenset[str]


def load_suite(
    path: Path,
    *,
    env: Mapping[str, str] | None = None,
    old_url: str | None = None,
    new_url: str | None = None,
) -> LoadedSuite:
    env = os.environ if env is None else env
    try:
        if path.stat().st_size > MAX_SUITE_BYTES:
            raise SuiteLoadError(f"{path} is larger than {MAX_SUITE_BYTES} bytes")
        # safe_load: plain data only. A suite file from someone else must
        # not be able to construct Python objects.
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SuiteLoadError(f"cannot read {path}: {exc.strerror}") from exc
    except UnicodeDecodeError as exc:
        raise SuiteLoadError(f"{path} is not UTF-8 text") from exc
    except yaml.YAMLError as exc:
        raise SuiteLoadError(f"{path} is not valid YAML: {exc}") from exc
    if not isinstance(document, dict):
        raise SuiteLoadError(f"{path} must contain a mapping at the top level")

    filler = _EnvFiller(env)
    document = filler.fill(document)
    if filler.missing:
        names = ", ".join(sorted(filler.missing))
        raise SuiteLoadError(f"environment variables not set: {names}")
    if filler.unusable:
        names = ", ".join(sorted(filler.unusable))
        raise SuiteLoadError(
            f"environment variables whose value contains '{{{{': {names}. "
            "That sequence starts a placeholder in a suite and cannot appear in a value."
        )
    secrets = filler.secrets

    # Command-line overrides let one suite file run against several
    # environments (local, staging) without editing it.
    targets = document.setdefault("targets", {})
    if isinstance(targets, dict):
        for side, url in (("old", old_url), ("new", new_url)):
            if url is not None:
                target = targets.setdefault(side, {})
                if isinstance(target, dict):
                    target["base_url"] = url

    try:
        suite = Suite.model_validate(document)
    except ValidationError as exc:
        # A message may quote the offending value, and that value may have
        # come from the environment.
        raise SuiteLoadError(Redactor(secrets).text(_describe(path, exc))) from None
    return LoadedSuite(suite=suite, secrets=frozenset(secrets))


class _EnvFiller:
    """Replaces ${NAME} throughout a document and records what it used."""

    def __init__(self, env: Mapping[str, str]) -> None:
        self._env = env
        self._nodes = 0
        self.missing: set[str] = set()
        self.unusable: set[str] = set()
        self.secrets: set[str] = set()

    def fill(self, value: Any) -> Any:
        self._nodes += 1
        if self._nodes > MAX_SUITE_NODES:
            raise SuiteLoadError("the suite is too large (does it use YAML anchors recursively?)")
        if isinstance(value, str):
            return _ENV_REFERENCE.sub(self._substitute, value)
        if isinstance(value, list):
            return [self.fill(item) for item in value]
        if isinstance(value, dict):
            return {key: self.fill(item) for key, item in value.items()}
        return value

    def _substitute(self, match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in self._env:
            self.missing.add(name)
            return match.group(0)
        value = self._env[name]
        if "{{" in value:
            # It would be read as a placeholder and expanded, or reported
            # by name in an error. Refuse it rather than risk either.
            self.unusable.add(name)
            return ""
        if value:
            self.secrets.add(value)
        return value


def _describe(path: Path, error: ValidationError) -> str:
    """Pydantic's errors, one per line, with the location written as a path."""
    lines = [f"{path} is not a valid suite:"]
    for problem in error.errors():
        where = ".".join(str(part) for part in problem["loc"]) or "(top level)"
        lines.append(f"  {where}: {problem['msg']}")
    return "\n".join(lines)
