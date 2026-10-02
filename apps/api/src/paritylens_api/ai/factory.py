"""Choosing the provider the deployment is configured for."""

from paritylens_api.ai.anthropic_provider import AnthropicProvider
from paritylens_api.ai.fake_provider import FakeProvider
from paritylens_api.ai.provider import LLMProvider
from paritylens_api.core.config import LlmProvider, Settings
from paritylens_api.models import Project


def provider_for(settings: Settings) -> LLMProvider | None:
    """The configured provider, or None when AI analysis is not set up."""
    match settings.llm_provider:
        case LlmProvider.ANTHROPIC:
            return AnthropicProvider(model=settings.llm_model, effort=settings.llm_effort)
        case LlmProvider.FAKE:
            return FakeProvider()
        case LlmProvider.NONE:
            return None


def initial_ai_status(project: Project, settings: Settings) -> str:
    """The AI status a freshly completed run starts with.

    Analysis sends response data to a third party, so it happens only when
    the project has opted in *and* the deployment has a provider.
    """
    if not project.ai_enabled:
        return "none"
    if settings.llm_provider is LlmProvider.NONE:
        return "skipped"
    return "pending"
