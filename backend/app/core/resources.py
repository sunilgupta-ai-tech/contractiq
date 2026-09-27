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
from app.llm.factory import create_embeddings, create_llm, create_vision
from app.llm.resilient import CircuitBreaker, ResilientLLM
from app.observability.llm_monitoring import MonitoredEmbeddings, MonitoredLLM
from app.observability.tracing import Exporter, LangfuseExporter, build_exporter
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
    _light_llm: LLMProvider | None = field(default=None, repr=False)
    _vision: LLMProvider | None = field(default=None, repr=False)
    _tracer: Exporter | None = field(default=None, repr=False)

    def vision(self) -> LLMProvider:
        """The image-captioning model (Phase 9), created on first use.

        Raises LLMConfigError if it is misconfigured (e.g. no API key).
        """
        if self._vision is None:
            self._vision = MonitoredLLM(
                create_vision(self.settings), role="vision", pricing=self.settings.llm_pricing
            )
        return self._vision

    def tracer(self) -> Exporter:
        """Where per-question traces go (Phase 13; see observability/tracing.py)."""
        if self._tracer is None:
            self._tracer = build_exporter(self.settings)
        return self._tracer

    def llm(self) -> LLMProvider:
        """The configured answer-generation model, created on first use.

        Raises LLMConfigError if it is misconfigured (e.g. no API key).
        """
        if self._llm is None:
            self._llm = self._resilient(None)
        return self._llm

    def light_llm(self) -> LLMProvider:
        """Phase 21 model routing: the lighter model for planning and query
        rewriting (LLM_LIGHT_MODEL), or the answer model when none is set."""
        if self._light_llm is None:
            model = self.settings.llm_light_model
            self._light_llm = self._resilient(model) if model else self.llm()
        return self._light_llm

    def _resilient(self, model: str | None) -> LLMProvider:
        """Monitored (Phase 13: tokens, latency, cost) and resilient (Phase 21:
        retry, fallback model, circuit breaker)."""
        settings = self.settings

        def monitored(name: str | None) -> LLMProvider:
            return MonitoredLLM(
                create_llm(settings, model=name), role="llm", pricing=settings.llm_pricing
            )

        return ResilientLLM(
            monitored(model),
            fallback=monitored(settings.llm_fallback_model)
            if settings.llm_fallback_model
            else None,
            max_retries=settings.llm_max_retries,
            breaker=CircuitBreaker(
                threshold=settings.llm_breaker_threshold, cooldown_s=settings.llm_breaker_cooldown_s
            ),
        )

    def embeddings(self) -> EmbeddingProvider:
        """The configured embedding provider (one shared HTTP client per process).

        Raises EmbeddingConfigError if it is misconfigured (e.g. no API key).
        """
        if self._embeddings is None:
            self._embeddings = MonitoredEmbeddings(create_embeddings(self.settings))
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
        if self._vision is not None:
            await self._vision.aclose()
        if isinstance(self._tracer, LangfuseExporter):
            await self._tracer.aclose()
