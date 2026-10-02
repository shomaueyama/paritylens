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
# The SDK's defaults are ten minutes and two retries: half an hour before
# a stuck call gives up. An analysis is not worth that long a wait.
_TIMEOUT_SECONDS = 120.0
_MAX_RETRIES = 1
_NO_CREDENTIALS = "the model provider has no API key configured"


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
        try:
            self._client = client or anthropic.AsyncAnthropic(
                timeout=_TIMEOUT_SECONDS, max_retries=_MAX_RETRIES
            )
        except anthropic.AnthropicError as exc:
            raise LLMError(_NO_CREDENTIALS) from exc

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
        except anthropic.APITimeoutError as exc:
            raise LLMError("the model provider took too long to answer") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("the model provider could not be reached") from exc
        except anthropic.CredentialsError as exc:
            raise LLMError(_NO_CREDENTIALS) from exc
        except anthropic.AnthropicError as exc:
            raise LLMError("the model provider's response could not be read") from exc
        except TypeError as exc:
            # What the SDK raises when it has no credentials to send.
            raise LLMError(_NO_CREDENTIALS) from exc
        return _answer(response)


def _answer(response: Any) -> dict[str, Any]:
    """The JSON object in a response, or LLMError saying why there is none."""
    try:
        stop_reason, content = response.stop_reason, response.content
        # A refusal is a successful HTTP response. It has to be checked
        # before the content is read: there may be none.
        if stop_reason == "refusal":
            raise LLMRefusedError("the model declined to analyse this run")
        if stop_reason == "max_tokens":
            raise LLMError("the model's answer was cut off")
        text = next((block.text for block in content if block.type == "text"), None)
    except (AttributeError, TypeError) as exc:
        # A proxy or gateway answered 200 with something that is not a
        # Messages response; the SDK hands it over as it came.
        raise LLMError("the model provider's response could not be read") from exc

    if text is None:
        raise LLMError("the model returned no answer")
    try:
        answer = json.loads(text)
    except (ValueError, RecursionError) as exc:
        raise LLMError("the model's answer was not valid JSON") from exc
    if not isinstance(answer, dict):
        raise LLMError("the model's answer was not a JSON object")
    return answer
