from app.services.llm import OpenAIProvider
from app.services.mock import MockLLMProvider
from app.services.openrouter import OpenRouterProvider


def create_llm_provider(settings, usage_path=None):
    if settings.is_test:
        return MockLLMProvider()
    if settings.llm_provider == "openrouter":
        return OpenRouterProvider(settings, usage_path)
    return OpenAIProvider(settings)
