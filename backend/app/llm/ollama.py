"""Ollama provider — local, zero-cost LLM and embeddings for development."""

from __future__ import annotations

import time

import httpx

from app.llm.base import (
    ChatMessage,
    EmbeddingError,
    EmbeddingTask,
    LLMBlockedError,
    LLMError,
    LLMResult,
)
from app.llm.embedding_utils import (
    check_llm_response,
    check_response,
    l2_normalize,
    validate_vectors,
)


class OllamaProvider:
    """Local answer generation via Ollama's /api/chat (e.g. llama3.1:8b)."""

    name = "ollama"

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_s: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model = model
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout_s, transport=transport)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def generate(
        self, messages: list[ChatMessage], *, temperature: float = 0.0, max_tokens: int = 1024
    ) -> LLMResult:
        started = time.perf_counter()
        try:
            response = await self._client.post(
                "/api/chat",
                json={
                    "model": self.model,
                    "messages": [{"role": m.role, "content": m.content} for m in messages],
                    "stream": False,
                    "options": {"temperature": temperature, "num_predict": max_tokens},
                },
            )
        except httpx.HTTPError as exc:  # Ollama not running, timeout
            raise LLMError(f"Ollama request failed: {type(exc).__name__}") from exc
        check_llm_response(response, "Ollama")
        body = response.json()
        text = (body.get("message") or {}).get("content") or ""
        if not text.strip():
            raise LLMBlockedError("Ollama returned no text")
        return LLMResult(
            text=text,
            model=self.model,
            prompt_tokens=body.get("prompt_eval_count"),
            completion_tokens=body.get("eval_count"),
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
        )


class OllamaEmbeddings:
    """Local embeddings via Ollama (e.g. nomic-embed-text, 768 dimensions).

    Ollama has no task-type parameter. Models trained with task prefixes
    (the nomic-embed family) instead expect the task written into the text
    itself — "search_document: ..." / "search_query: ..." — so it is added
    here for those models. Without it, their retrieval quality drops.
    """

    name = "ollama"
    _NOMIC_PREFIXES = {
        EmbeddingTask.DOCUMENT: "search_document: ",
        EmbeddingTask.QUERY: "search_query: ",
    }

    def __init__(
        self,
        base_url: str,
        model: str,
        dimension: int,
        timeout_s: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model = model
        self.dimension = dimension
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout_s, transport=transport)

    async def embed(
        self, texts: list[str], *, task: EmbeddingTask = EmbeddingTask.DOCUMENT
    ) -> list[list[float]]:
        if not texts:
            return []
        if self.model.startswith("nomic-embed"):
            texts = [self._NOMIC_PREFIXES[task] + t for t in texts]
        try:
            response = await self._client.post(
                "/api/embed", json={"model": self.model, "input": texts}
            )
        except httpx.HTTPError as exc:  # Ollama not running, timeout
            raise EmbeddingError(f"Ollama embeddings request failed: {type(exc).__name__}") from exc
        check_response(response, "Ollama")
        vectors = [l2_normalize(v) for v in response.json().get("embeddings", [])]
        validate_vectors(
            vectors, expected_count=len(texts), dimension=self.dimension, provider="Ollama"
        )
        return vectors

    async def aclose(self) -> None:
        await self._client.aclose()
