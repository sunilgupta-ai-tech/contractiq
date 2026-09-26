"""Gemini provider — optional hosted LLM. The key is read from backend
settings only; verify current pricing, quotas and model availability before
production use."""

from __future__ import annotations

import base64
import time

import httpx

from app.core.logging import get_logger
from app.llm.base import (
    ChatMessage,
    EmbeddingConfigError,
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

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

logger = get_logger(__name__)


class GeminiProvider:
    """Answer generation with Gemini (POST /models/{model}:generateContent).

    System messages go into `systemInstruction` (Gemini's separate slot for
    them), the rest into `contents` with roles user/model.
    """

    name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout_s: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,  # tests inject a mock
        thinking_budget: int | None = None,
    ) -> None:
        self.model = model
        # Gemini 2.5 models "think" before answering, and thinking tokens count
        # against maxOutputTokens (and are billed as output). None = model
        # default; 0 = no thinking (2.5 Flash), which keeps short structured
        # replies from being cut off and costs less.
        self.thinking_budget = thinking_budget
        # Key goes in a header, not the URL, so it never lands in access logs.
        self._client = httpx.AsyncClient(
            base_url=_BASE_URL,
            timeout=timeout_s,
            headers={"x-goog-api-key": api_key},
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def generate(
        self, messages: list[ChatMessage], *, temperature: float = 0.0, max_tokens: int = 1024
    ) -> LLMResult:
        started = time.perf_counter()
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        contents = [
            {"role": "model" if m.role == "assistant" else "user", "parts": _parts(m)}
            for m in messages
            if m.role != "system"
        ]
        config: dict[str, object] = {"temperature": temperature, "maxOutputTokens": max_tokens}
        if self.thinking_budget is not None:
            config["thinkingConfig"] = {"thinkingBudget": self.thinking_budget}
        payload: dict[str, object] = {"contents": contents, "generationConfig": config}
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        try:
            response = await self._client.post(
                f"/models/{self.model}:generateContent", json=payload
            )
        except httpx.HTTPError as exc:
            raise LLMError(f"Gemini request failed: {type(exc).__name__}") from exc
        check_llm_response(response, "Gemini")
        body = response.json()
        usage = body.get("usageMetadata", {})
        # No candidate, or a candidate without text, means the response was
        # blocked (safety filter, recitation) — report it, don't crash on it.
        candidates = body.get("candidates") or []
        parts = (candidates[0].get("content") or {}).get("parts") if candidates else None
        text = "".join(p.get("text", "") for p in parts or [])
        if not text.strip():
            reason = candidates[0].get("finishReason") if candidates else "NO_CANDIDATES"
            raise LLMBlockedError(f"Gemini returned no text (finishReason={reason})")
        if candidates[0].get("finishReason") == "MAX_TOKENS":
            # The reply was cut off (often by thinking tokens using the budget).
            logger.warning("llm_truncated", extra={"model": self.model, "max_tokens": max_tokens})
        # Thinking tokens are billed as output: count them, or cost is understated.
        completion = usage.get("candidatesTokenCount")
        if usage.get("thoughtsTokenCount"):
            completion = (completion or 0) + usage["thoughtsTokenCount"]
        return LLMResult(
            text=text,
            model=self.model,
            prompt_tokens=usage.get("promptTokenCount"),
            completion_tokens=completion,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
        )


def _parts(message: ChatMessage) -> list[dict[str, object]]:
    """Images first, then the text: Google recommends image-before-prompt
    ordering for single-image requests. Images travel inline (base64), which
    suits contract figures — far below the 20 MB inline request limit."""
    parts: list[dict[str, object]] = [
        {"inlineData": {"mimeType": "image/png", "data": base64.b64encode(image).decode()}}
        for image in message.images
    ]
    parts.append({"text": message.content})
    return parts


class GeminiEmbeddings:
    """Gemini text embeddings (default model: gemini-embedding-001).

    API: POST /models/{model}:batchEmbedContents, up to 100 texts per call.
    Each request carries:
      * taskType  RETRIEVAL_DOCUMENT for chunks, RETRIEVAL_QUERY for questions
                  (Gemini embeds the two asymmetrically; see EmbeddingTask)
      * outputDimensionality  so vectors match the Qdrant collection size
                  (768 here; the model supports 128-3072)

    Privacy note: chunk text is sent to Google. Check the data-processing
    terms of the Gemini API tier in use before indexing client contracts.
    """

    name = "gemini"
    MAX_BATCH = 100
    _TASK_TYPES = {
        EmbeddingTask.DOCUMENT: "RETRIEVAL_DOCUMENT",
        EmbeddingTask.QUERY: "RETRIEVAL_QUERY",
    }

    def __init__(
        self,
        api_key: str,
        model: str,
        dimension: int,
        timeout_s: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,  # tests inject a mock
    ) -> None:
        self.model = model
        self.dimension = dimension
        self._client = httpx.AsyncClient(
            base_url=_BASE_URL,
            timeout=timeout_s,
            # Key in a header, never in the URL, so it can't leak into logs.
            headers={"x-goog-api-key": api_key},
            transport=transport,
        )

    async def embed(
        self, texts: list[str], *, task: EmbeddingTask = EmbeddingTask.DOCUMENT
    ) -> list[list[float]]:
        if not texts:
            return []
        if len(texts) > self.MAX_BATCH:
            raise EmbeddingConfigError(f"Gemini accepts at most {self.MAX_BATCH} texts per call")
        payload = {
            "requests": [
                {
                    "model": f"models/{self.model}",
                    "content": {"parts": [{"text": text}]},
                    "taskType": self._TASK_TYPES[task],
                    "outputDimensionality": self.dimension,
                }
                for text in texts
            ]
        }
        try:
            response = await self._client.post(
                f"/models/{self.model}:batchEmbedContents", json=payload
            )
        except httpx.HTTPError as exc:  # timeouts, connection resets, DNS
            raise EmbeddingError(f"Gemini embeddings request failed: {type(exc).__name__}") from exc
        check_response(response, "Gemini")
        vectors = [l2_normalize(e["values"]) for e in response.json().get("embeddings", [])]
        validate_vectors(
            vectors, expected_count=len(texts), dimension=self.dimension, provider="Gemini"
        )
        return vectors

    async def aclose(self) -> None:
        await self._client.aclose()
