"""An LLMProvider that needs no network and no key.

Used by tests, and by local demos (PARITYLENS_LLM_PROVIDER=fake) so the
whole flow can be seen without an account anywhere. Its opinions are
rules of thumb written here, clearly labelled as coming from "fake".
"""

import json
from collections.abc import Callable
from typing import Any

type Responder = Callable[[dict[str, Any]], dict[str, Any]]


def _rule_of_thumb(request: dict[str, Any]) -> dict[str, Any]:
    verdicts = {"critical": "breaking", "high": "breaking", "medium": "warning", "low": "safe"}
    return {
        "analyses": [
            {
                "finding_id": finding["id"],
                "verdict": verdicts.get(finding["severity"], "warning"),
                "confidence": "low",
                "explanation": (
                    f"[fake provider] A {finding['kind']} at {finding['path']} "
                    f"rated {finding['severity']} by the deterministic comparison."
                ),
            }
            for finding in request["findings"]
        ]
    }


class FakeProvider:
    name = "fake"
    model = "fake-1"

    def __init__(self, responder: Responder | None = None) -> None:
        self._respond = responder or _rule_of_thumb
        # What it was asked, for tests to inspect.
        self.calls: list[dict[str, Any]] = []

    async def complete_json(
        self, *, system: str, user: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        self.calls.append({"system": system, "user": user, "schema": schema})
        return self._respond(json.loads(user))
