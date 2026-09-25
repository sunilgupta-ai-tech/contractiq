"""
Embedding orchestration: batching, retries and a content-hash cache on top
of whichever EmbeddingProvider is configured (Gemini by default).

Flow for a list of texts
------------------------
    1. look up each text in the Redis cache      (key = tenant + model + task + sha256(text))
    2. send only the misses to the provider, in batches of EMBEDDING_BATCH_SIZE
    3. retry temporary failures with exponential backoff + jitter
    4. store the new vectors in the cache, return all vectors in input order

Why a cache
-----------
Contracts are revised, not rewritten: version 2 of an MSA usually shares
most clauses with version 1. Identical text gives an identical vector, so a
cache hit skips a paid API call. Keys include the model and dimension, so
changing either can never return a stale vector, and the tenant, following
the rule that every cache key is tenant-scoped (app/cache/redis.py).

The cache is an optimisation only: if Redis is unavailable, embedding
continues without it (logged), rather than failing documents.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import random
from array import array
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.cache.redis import tenant_cache_key
from app.core.config import Settings
from app.core.logging import get_logger
from app.llm.base import EmbeddingConfigError, EmbeddingError, EmbeddingProvider, EmbeddingTask

logger = get_logger(__name__)

# Gemini's embedding input limit is 2,048 tokens; at ~4 chars per token this
# stays safely inside it. Chunks are far smaller (Phase 5 caps them), so this
# only guards against a pathological input.
MAX_EMBED_CHARS = 8000
_MAX_BACKOFF_S = 30.0


@dataclass
class EmbeddingStats:
    """Reported per document in extraction_metadata (cost visibility)."""

    texts: int = 0
    cache_hits: int = 0
    api_calls: int = 0
    retries: int = 0


class EmbeddingService:
    def __init__(
        self,
        provider: EmbeddingProvider,
        settings: Settings,
        redis: Redis | None = None,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,  # tests skip real waits
    ) -> None:
        self.provider = provider
        self.redis = redis
        self.batch_size = max(1, settings.embedding_batch_size)
        self.max_retries = settings.embedding_max_retries
        self.cache_ttl_s = settings.embedding_cache_ttl_s
        self._sleep = sleep

    async def embed_documents(
        self, texts: list[str], *, tenant_id: str
    ) -> tuple[list[list[float]], EmbeddingStats]:
        """Vectors for chunk texts, in the same order as `texts`."""
        return await self._embed(texts, EmbeddingTask.DOCUMENT, tenant_id)

    async def embed_query(self, text: str, *, tenant_id: str) -> list[float]:
        """Vector for a user question (used by retrieval in Phase 7)."""
        vectors, _ = await self._embed([text], EmbeddingTask.QUERY, tenant_id)
        return vectors[0]

    async def _embed(
        self, texts: list[str], task: EmbeddingTask, tenant_id: str
    ) -> tuple[list[list[float]], EmbeddingStats]:
        stats = EmbeddingStats(texts=len(texts))
        texts = [t[:MAX_EMBED_CHARS] for t in texts]
        keys = [self._cache_key(tenant_id, task, t) for t in texts]
        results: list[list[float] | None] = await self._cache_get(keys)
        stats.cache_hits = sum(v is not None for v in results)

        missing = [i for i, v in enumerate(results) if v is None]
        fresh: dict[int, list[float]] = {}
        for start in range(0, len(missing), self.batch_size):
            batch = missing[start : start + self.batch_size]
            vectors = await self._call_with_retry([texts[i] for i in batch], task, stats)
            fresh.update(zip(batch, vectors, strict=True))
        for i, vector in fresh.items():
            results[i] = vector

        await self._cache_set({keys[i]: v for i, v in fresh.items()})
        return [v for v in results if v is not None], stats

    async def _call_with_retry(
        self, texts: list[str], task: EmbeddingTask, stats: EmbeddingStats
    ) -> list[list[float]]:
        """Call the provider; on a temporary error wait 1s, 2s, 4s ... (capped,
        plus random jitter so parallel workers don't retry in lock-step)."""
        attempt = 0
        while True:
            stats.api_calls += 1
            try:
                return await self.provider.embed(texts, task=task)
            except EmbeddingConfigError:
                raise  # retrying can't fix a bad key or a bad request
            except EmbeddingError:
                if attempt >= self.max_retries:
                    raise
                delay = min(2**attempt, _MAX_BACKOFF_S) + random.uniform(0, 1)  # noqa: S311
                logger.warning(
                    "embedding_retry",
                    extra={"attempt": attempt + 1, "delay_s": round(delay, 2)},
                )
                stats.retries += 1
                attempt += 1
                await self._sleep(delay)

    # --- cache ---------------------------------------------------------------------

    def _cache_key(self, tenant_id: str, task: EmbeddingTask, text: str) -> str:
        digest = hashlib.sha256(text.encode()).hexdigest()
        model = f"{self.provider.name}:{self.provider.model}:{self.provider.dimension}"
        return tenant_cache_key(tenant_id, "emb", f"{model}:{task.value}:{digest}")

    async def _cache_get(self, keys: list[str]) -> list[list[float] | None]:
        if not self.redis or not self.cache_ttl_s or not keys:
            return [None] * len(keys)
        try:
            raw = await self.redis.mget(keys)
        except RedisError as exc:
            logger.warning("embedding_cache_unavailable", extra={"error": repr(exc)})
            return [None] * len(keys)
        return [_decode(v) if v else None for v in raw]

    async def _cache_set(self, entries: dict[str, list[float]]) -> None:
        if not self.redis or not self.cache_ttl_s or not entries:
            return
        try:
            async with self.redis.pipeline(transaction=False) as pipe:
                for key, vector in entries.items():
                    pipe.set(key, _encode(vector), ex=self.cache_ttl_s)
                await pipe.execute()
        except RedisError as exc:
            logger.warning("embedding_cache_unavailable", extra={"error": repr(exc)})


def _encode(vector: list[float]) -> str:
    """float32 bytes, base64 — ~4 KB for 768 dims (vs ~15 KB as JSON). The
    shared Redis client decodes responses to str, hence base64, not raw bytes."""
    return base64.b64encode(array("f", vector).tobytes()).decode()


def _decode(value: str) -> list[float]:
    floats = array("f")
    floats.frombytes(base64.b64decode(value))
    return floats.tolist()
