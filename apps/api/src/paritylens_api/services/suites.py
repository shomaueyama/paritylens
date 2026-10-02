"""Turning a project's stored configuration into a Suite the engine can run."""

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from paritylens_engine.model import RuleSet, UnorderedRule
from paritylens_engine.suite import Suite

from paritylens_api.core.errors import InvalidRequestError
from paritylens_api.models import Project, Rule, TestCase
from paritylens_api.schemas.projects import SECRET_REFERENCE


def ruleset_for(project: Project, rules: Sequence[Rule]) -> RuleSet:
    return RuleSet(
        ignore=tuple(rule.path for rule in rules if rule.kind == "ignore"),
        critical=tuple(rule.path for rule in rules if rule.kind == "critical"),
        unordered=tuple(
            UnorderedRule(path=rule.path, key=rule.options.get("key"))
            for rule in rules
            if rule.kind == "unordered"
        ),
        compare_headers=tuple(rule.path for rule in rules if rule.kind == "compare_header"),
        critical_field_names=project.critical_field_names,
    )


def suite_snapshot(
    project: Project, cases: Sequence[TestCase], rules: Sequence[Rule]
) -> dict[str, Any]:
    """What a queued run stores: the suite as it stands now, and where it came from.

    {"suite": <a Suite as JSON>, "test_case_ids": [<id of each case, in order>]}

    Secrets are still referred to by name here. Their values are filled in
    only at the moment the worker executes the run, so they are never
    written to the runs table.
    """
    enabled = [case for case in cases if case.enabled]
    if not enabled:
        raise InvalidRequestError("the project has no enabled test cases to run")
    suite = {
        "targets": {
            "old": {"base_url": project.old_base_url, "headers": project.old_headers},
            "new": {"base_url": project.new_base_url, "headers": project.new_headers},
        },
        "rules": ruleset_for(project, rules).model_dump(mode="json"),
        "cases": [
            {"name": case.name, "steps": case.steps, "noise_detection": case.noise_detection}
            for case in enabled
        ],
    }
    # Validate now, so a problem is reported to the person starting the run
    # and not discovered later by the worker.
    Suite.model_validate(suite)
    return {"suite": suite, "test_case_ids": [str(case.id) for case in enabled]}


def referenced_secrets(snapshot: Mapping[str, Any]) -> set[str]:
    names: set[str] = set()
    for side in ("old", "new"):
        for value in snapshot["suite"]["targets"][side].get("headers", {}).values():
            names.update(SECRET_REFERENCE.findall(value))
    return names


def resolve_suite(snapshot: Mapping[str, Any], secrets: Mapping[str, str]) -> Suite:
    """Fill in {{secret.NAME}} references and build the Suite to execute."""

    def fill(value: str) -> str:
        return SECRET_REFERENCE.sub(lambda match: secrets[match.group(1)], value)

    suite = snapshot["suite"]
    targets = {
        side: {
            "base_url": suite["targets"][side]["base_url"],
            "headers": {
                name: fill(value)
                for name, value in suite["targets"][side].get("headers", {}).items()
            },
        }
        for side in ("old", "new")
    }
    return Suite.model_validate({**suite, "targets": targets})


def snapshot_case_ids(snapshot: Mapping[str, Any]) -> list[uuid.UUID]:
    return [uuid.UUID(value) for value in snapshot.get("test_case_ids", [])]
