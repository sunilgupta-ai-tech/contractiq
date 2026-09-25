from __future__ import annotations

from app.core.config import LLMProviderName, Settings
from app.llm.base import EmbeddingProvider, LLMProvider


def create_llm(settings: Settings) -> LLMProvider:
    if settings.llm_provider is LLMProviderName.GEMINI:
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is required when LLM_PROVIDER=gemini")
        from app.llm.gemini import GeminiProvider

        return GeminiProvider(settings.gemini_api_key.get_secret_value(), settings.gemini_model)
    from app.llm.ollama import OllamaProvider

    return OllamaProvider(settings.ollama_base_url, settings.ollama_model)


def create_embeddings(settings: Settings) -> EmbeddingProvider:
    from app.llm.ollama import OllamaEmbeddings

    return OllamaEmbeddings(
        settings.ollama_base_url, settings.embedding_model, settings.embedding_dimension
    )
