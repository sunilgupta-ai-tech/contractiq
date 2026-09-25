"""
Process-wide infrastructure clients.

Created once in the FastAPI lifespan (and in the worker's startup hook) and
closed on shutdown. Holding them in one explicit object — rather than
module-level globals — keeps dependencies visible and trivially replaceable
in tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from arq.connections import ArqRedis
from qdrant_client import AsyncQdrantClient
from redis.asyncio import Redis

from app.cache.redis import create_redis
from app.core.config import Settings
from app.core.logging import get_logger
from app.db.database import Database
from app.llm.base import EmbeddingProvider, LLMProvider
from app.llm.factory import create_embeddings, create_llm
from app.queue import create_queue
from app.storage import ObjectStorage, create_storage
from app.vectorstore.collections import ensure_collection
from app.vectorstore.qdrant import create_qdrant

logger = get_logger(__name__)


@dataclass
class Resources:
    settings: Settings
    db: Database
    redis: Redis
    qdrant: AsyncQdrantClient
    storage: ObjectStorage
    queue: ArqRedis
    # Created on first use (see `embeddings()`), not at startup: a missing
    # GEMINI_API_KEY must not stop the API from booting in development.
    _embeddings: EmbeddingProvider | None = field(default=None, repr=False)
    _llm: LLMProvider | None = field(default=None, repr=False)

    def llm(self) -> LLMProvider:
        """The configured answer-generation model, created on first use.

        Raises LLMConfigError if it is misconfigured (e.g. no API key).
        """
        if self._llm is None:
            self._llm = create_llm(self.settings)
        return self._llm

    def embeddings(self) -> EmbeddingProvider:
        """The configured embedding provider (one shared HTTP client per process).

        Raises EmbeddingConfigError if it is misconfigured (e.g. no API key).
        """
        if self._embeddings is None:
            self._embeddings = create_embeddings(self.settings)
        return self._embeddings

    @classmethod
    def create(cls, settings: Settings) -> Resources:
        return cls(
            settings=settings,
            db=Database(settings),
            redis=create_redis(settings),
            qdrant=create_qdrant(settings),
            storage=create_storage(settings),
            queue=create_queue(settings),
        )

    async def bootstrap(self) -> None:
        """Best-effort idempotent setup. Failure is logged, not fatal: the
        API should still start and report not-ready via /ready, so the
        orchestrator (ECS/k8s) can hold traffic until dependencies recover."""
        try:
            await ensure_collection(
                self.qdrant, self.settings.qdrant_collection, self.settings.embedding_dimension
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("qdrant_bootstrap_failed", extra={"error": str(exc)})

    async def close(self) -> None:
        await self.db.dispose()
        await self.redis.aclose()
        await self.queue.aclose()
        await self.queue.connection_pool.disconnect()  # explicit pools aren't auto-closed
        await self.qdrant.close()
        if self._embeddings is not None:
            await self._embeddings.aclose()
        if self._llm is not None:
            await self._llm.aclose()
