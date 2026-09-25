"""
A deterministic stand-in for Gemini/Ollama in tests.

Vectors are derived from a hash of the text, so the same text always gets
the same unit vector and different texts get different ones. That is enough
to test batching, caching, indexing and tenant-filtered search against a real
Qdrant — without network calls or API keys.
"""

from __future__ import annotations

import hashlib
import math
import random

from app.llm.base import EmbeddingTask


class FakeEmbeddings:
    name = "fake"
    model = "hash-embed"

    def __init__(self, dimension: int = 768) -> None:
        self.dimension = dimension
        self.calls: list[list[str]] = []  # every batch received, for assertions

    async def embed(
        self, texts: list[str], *, task: EmbeddingTask = EmbeddingTask.DOCUMENT
    ) -> list[list[float]]:
        self.calls.append(list(texts))
        return [vector_for(t, self.dimension) for t in texts]

    async def aclose(self) -> None:
        return None


def vector_for(text: str, dimension: int = 768) -> list[float]:
    seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")
    rng = random.Random(seed)  # noqa: S311 — test data, not security
    raw = [rng.uniform(-1, 1) for _ in range(dimension)]
    norm = math.sqrt(sum(v * v for v in raw))
    return [v / norm for v in raw]
