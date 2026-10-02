"""LLMProvider backed by Claude, through Anthropic's SDK.

The only module that imports `anthropic`.
"""

import json
from typing import Any, Literal

import anthropic

from paritylens_api.ai.provider import LLMError, LLMRefusedError

type Effort = Literal["low", "medium", "high", "xhigh", "max"]

# Beta that enables fallbacks="default": if a safety classifier declines
# the request, the API re-runs it on another model in the same call.
_FALLBACK_BETA = "server-side-fallback-2026-07-01"
_MAX_TOKENS = 16000


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        *,
        model: str,
        effort: Effort,
        client: anthropic.AsyncAnthropic | None = None,
    ) -> None:
        self.model = model
        self._effort: Effort = effort
        # Zero-argument construction: the SDK finds credentials itself
        # (ANTHROPIC_API_KEY, or a profile from `ant auth login`).
        self._client = client or anthropic.AsyncAnthropic()

    async def complete_json(
        self, *, system: str, user: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            response = await self._client.beta.messages.create(
                model=self.model,
                max_tokens=_MAX_TOKENS,
                betas=[_FALLBACK_BETA],
                fallbacks="default",
                # The system prompt is identical on every call, so it is
                # marked cacheable. Too short a prefix is simply not cached.
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                output_config={
                    "effort": self._effort,
                    # Constrains the reply to this JSON schema, so there
                    # is no free text to parse.
                    "format": {"type": "json_schema", "schema": schema},
                },
                messages=[{"role": "user", "content": user}],
            )
        # Most specific first. Messages name what happened without quoting
        # the request, which contains data from the APIs under test.
        except anthropic.AuthenticationError as exc:
            raise LLMError("the model provider rejected the API key") from exc
        except anthropic.RateLimitError as exc:
            raise LLMError("the model provider is rate limiting requests") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"the model provider answered {exc.status_code}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("the model provider could not be reached") from exc

        # A refusal is a successful HTTP response. It has to be checked
        # before the content is read: there may be none.
        if response.stop_reason == "refusal":
            raise LLMRefusedError("the model declined to analyse this run")
        if response.stop_reason == "max_tokens":
            raise LLMError("the model's answer was cut off")

        text = next((block.text for block in response.content if block.type == "text"), None)
        if text is None:
            raise LLMError("the model returned no answer")
        try:
            answer = json.loads(text)
        except ValueError as exc:
            raise LLMError("the model's answer was not valid JSON") from exc
        if not isinstance(answer, dict):
            raise LLMError("the model's answer was not a JSON object")
        return answer
