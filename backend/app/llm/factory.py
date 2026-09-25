from __future__ import annotations

from app.core.config import LLMProviderName, Settings
from app.llm.base import EmbeddingConfigError, EmbeddingProvider, LLMConfigError, LLMProvider


def create_llm(settings: Settings) -> LLMProvider:
    """The answer-generation model chosen by LLM_PROVIDER (gemini | ollama).

    Raises LLMConfigError if Gemini is selected without a key.
    """
    if settings.llm_provider is LLMProviderName.GEMINI:
        if not settings.gemini_api_key:
            raise LLMConfigError("GEMINI_API_KEY is required when LLM_PROVIDER=gemini")
        from app.llm.gemini import GeminiProvider

        return GeminiProvider(
            settings.gemini_api_key.get_secret_value(),
            settings.gemini_model,
            timeout_s=settings.llm_timeout_s,
        )
    from app.llm.ollama import OllamaProvider

    return OllamaProvider(
        settings.ollama_base_url, settings.ollama_model, timeout_s=settings.llm_timeout_s
    )


def create_embeddings(settings: Settings) -> EmbeddingProvider:
    """The embedding provider chosen by EMBEDDING_PROVIDER (gemini | ollama).

    Raises EmbeddingConfigError (not retried) if Gemini is selected without a
    key, so a worker fails the job immediately with a clear reason.
    """
    if settings.embedding_provider is LLMProviderName.GEMINI:
        if not settings.gemini_api_key:
            raise EmbeddingConfigError("GEMINI_API_KEY is required when EMBEDDING_PROVIDER=gemini")
        from app.llm.gemini import GeminiEmbeddings

        return GeminiEmbeddings(
            settings.gemini_api_key.get_secret_value(),
            settings.embedding_model,
            settings.embedding_dimension,
            timeout_s=settings.embedding_timeout_s,
        )
    from app.llm.ollama import OllamaEmbeddings

    return OllamaEmbeddings(
        settings.ollama_base_url,
        settings.embedding_model,
        settings.embedding_dimension,
        timeout_s=settings.embedding_timeout_s,
    )
