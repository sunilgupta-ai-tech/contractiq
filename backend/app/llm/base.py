"""
LLM provider abstraction.

Business logic depends on `LLMProvider`, not on Gemini/Ollama SDKs, so the
model can be swapped (hosted ↔ local) by configuration alone. API keys live
only in backend settings and are never sent to the browser.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol


@dataclass(frozen=True)
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class LLMResult:
    text: str
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    latency_ms: float | None = None


class LLMProvider(Protocol):
    name: str

    async def generate(
        self, messages: list[ChatMessage], *, temperature: float = 0.0, max_tokens: int = 1024
    ) -> LLMResult: ...


class EmbeddingTask(StrEnum):
    """What a text will be used for.

    Retrieval embedding models are trained asymmetrically: a *question* and
    the *passage* that answers it are embedded slightly differently. Telling
    the model which one it is embedding measurably improves search quality.
    Chunks are always DOCUMENT; user questions (Phase 7) are QUERY.
    """

    DOCUMENT = "document"
    QUERY = "query"


class EmbeddingError(Exception):
    """A temporary failure (rate limit, 5xx, timeout, network). Retried."""


class EmbeddingConfigError(EmbeddingError):
    """A failure retrying cannot fix: invalid/missing API key, unknown model,
    malformed request, or a response of the wrong size. Raised immediately so
    a misconfiguration is visible at once instead of after minutes of retries."""


class EmbeddingProvider(Protocol):
    """Turns texts into vectors. One call = one batch (the service batches)."""

    name: str
    model: str
    dimension: int

    async def embed(
        self, texts: list[str], *, task: EmbeddingTask = EmbeddingTask.DOCUMENT
    ) -> list[list[float]]: ...

    async def aclose(self) -> None: ...
