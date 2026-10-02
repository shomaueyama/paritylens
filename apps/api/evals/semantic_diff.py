"""Compare the model's verdicts with expected ones on a fixed set of findings.

    uv run python apps/api/evals/semantic_diff.py

Calls the real API (one request), so it costs money and is not part of CI.
See README.md in this directory.
"""

import asyncio
import json
from pathlib import Path

from paritylens_api.ai.analyzer import Finding, request_analysis
from paritylens_api.ai.factory import provider_for
from paritylens_api.core.config import LlmProvider, Settings


async def main() -> None:
    cases = json.loads((Path(__file__).parent / "cases.json").read_text(encoding="utf-8"))
    expected = {case["id"]: case.pop("expected") for case in cases}
    findings = [Finding(id=case["id"], signature=case["id"], document=case) for case in cases]

    settings = Settings(_env_file=None, llm_provider=LlmProvider.ANTHROPIC)  # type: ignore[call-arg]
    provider = provider_for(settings)
    if provider is None:
        raise SystemExit("no provider configured")
    analyses = await request_analysis(provider, findings)

    agreed = 0
    for case in cases:
        analysis = analyses.get(case["id"])
        verdict = analysis.verdict if analysis else "(none)"
        match = verdict == expected[case["id"]]
        agreed += match
        mark = "ok " if match else "DIFF"
        print(
            f"{mark} {case['id']:<4} {case['kind']:<16} {case['path']:<24} "
            f"expected {expected[case['id']]:<9} got {verdict}"
        )
        if analysis and not match:
            print(f"       {analysis.explanation}")
    print(f"\n{agreed}/{len(cases)} agree  (model {provider.model})")


if __name__ == "__main__":
    asyncio.run(main())
