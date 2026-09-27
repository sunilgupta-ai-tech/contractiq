"""
Per-call model monitoring (Phase 13): model, tokens, latency, cost and
outcome for every LLM / vision / embedding call, plus one record per
answered question (prompt version, cited chunk ids, groundedness).

How it attaches
---------------
`Resources.llm()`, `.vision()` and `.embeddings()` return the providers
wrapped in MonitoredLLM / MonitoredEmbeddings, so every existing caller —
Q&A, the agent, clause extraction, summaries, captioning, evaluation — is
measured without changing a line of it. Each call:

    * updates Prometheus metrics (metrics.py; no tenant labels)
    * logs an `llm_call` line; the log context adds request_id and tenant_id,
      which is how per-tenant usage and cost are reported
    * is added to the current request's trace, if one is open (tracing.py)

Cost
----
LLM_PRICING maps a model name to USD per million input/output tokens:

    LLM_PRICING='{"gemini-2.5-flash": {"input_per_mtok": 0.30, "output_per_mtok": 2.50}}'

There are deliberately no built-in prices: they change, differ by tier and
region, and a stale hard-coded price is worse than none. Take the values
from the provider's current price list. Unpriced models report tokens only.
Local models (Ollama) cost nothing per call.

Nothing here logs prompt or answer text: only sizes, ids and numbers.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from app.chunking.tokens import estimate_tokens
from app.core.logging import get_logger
from app.llm.base import (
    ChatMessage,
    EmbeddingProvider,
    EmbeddingTask,
    LLMBlockedError,
    LLMConfigError,
    LLMError,
    LLMProvider,
    LLMResult,
)
from app.observability import metrics
from app.observability.tracing import record_generation
from app.services import usage

if TYPE_CHECKING:
    from app.rag.pipelines.qa import RagAnswer

logger = get_logger("contractiq.llm")

Pricing = Mapping[str, Mapping[str, float]]


def estimate_cost(
    pricing: Pricing, model: str, prompt_tokens: int | None, completion_tokens: int | None
) -> float | None:
    """USD for one call, or None when the model has no configured price."""
    price = pricing.get(model)
    if price is None:
        return None
    return (
        (prompt_tokens or 0) * price.get("input_per_mtok", 0.0)
        + (completion_tokens or 0) * price.get("output_per_mtok", 0.0)
    ) / 1_000_000


class MonitoredLLM:
    """An LLMProvider that measures every `generate` call of the one it wraps."""

    def __init__(self, inner: LLMProvider, *, role: str, pricing: Pricing | None = None) -> None:
        self.inner = inner
        self.role = role  # "llm" (answers, extraction, summaries) or "vision"
        self.pricing = pricing or {}
        self.name = inner.name
        self.model = inner.model

    async def generate(
        self, messages: list[ChatMessage], *, temperature: float = 0.0, max_tokens: int = 1024
    ) -> LLMResult:
        started = time.perf_counter()
        outcome = "ok"
        result: LLMResult | None = None
        try:
            result = await self.inner.generate(
                messages, temperature=temperature, max_tokens=max_tokens
            )
            return result
        except LLMConfigError:
            outcome = "config_error"
            raise
        except LLMBlockedError:
            outcome = "blocked"
            raise
        except LLMError:
            outcome = "error"
            raise
        finally:
            self._record(started, outcome, result, images=sum(len(m.images) for m in messages))

    def _record(
        self, started: float, outcome: str, result: LLMResult | None, *, images: int
    ) -> None:
        seconds = time.perf_counter() - started
        labels = {"role": self.role, "provider": self.name, "model": self.model}
        metrics.LLM_CALLS.labels(**labels, outcome=outcome).inc()
        metrics.LLM_LATENCY.labels(**labels).observe(seconds)
        prompt = result.prompt_tokens if result else None
        completion = result.completion_tokens if result else None
        if result is not None:
            usage.add_llm(prompt, completion)  # Phase 22: the organization's AI usage
        if prompt:
            metrics.LLM_TOKENS.labels(**labels, kind="prompt").inc(prompt)
        if completion:
            metrics.LLM_TOKENS.labels(**labels, kind="completion").inc(completion)
        cost = estimate_cost(self.pricing, self.model, prompt, completion) if result else None
        if cost:
            metrics.LLM_COST.labels(**labels).inc(cost)
        latency_ms = round(seconds * 1000, 1)
        logger.info(
            "llm_call",
            extra={
                **labels,
                "outcome": outcome,
                "latency_ms": latency_ms,
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "cost_usd": round(cost, 6) if cost is not None else None,
                "images": images,
            },
        )
        record_generation(
            name=self.role,
            model=f"{self.name}:{self.model}",
            duration_ms=latency_ms,
            prompt_tokens=prompt,
            completion_tokens=completion,
            cost_usd=cost,
            outcome=outcome,
        )

    async def aclose(self) -> None:
        await self.inner.aclose()


class MonitoredEmbeddings:
    """An EmbeddingProvider that measures every `embed` call (one batch)."""

    def __init__(self, inner: EmbeddingProvider) -> None:
        self.inner = inner
        self.name = inner.name
        self.model = inner.model
        self.dimension = inner.dimension

    async def embed(
        self, texts: list[str], *, task: EmbeddingTask = EmbeddingTask.DOCUMENT
    ) -> list[list[float]]:
        started = time.perf_counter()
        try:
            vectors = await self.inner.embed(texts, task=task)
            usage.add_embedding(sum(estimate_tokens(t) for t in texts))
            return vectors
        finally:
            labels = {"provider": self.name, "model": self.model}
            metrics.EMBEDDING_TEXTS.labels(**labels).inc(len(texts))
            metrics.EMBEDDING_LATENCY.labels(**labels).observe(time.perf_counter() - started)

    async def aclose(self) -> None:
        await self.inner.aclose()


def record_answer(result: RagAnswer, *, mode: str, withheld: bool, latency_ms: int) -> str:
    """Metrics + one `rag_answer` log line per /query answer. Returns the outcome."""
    from app.rag.pipelines.qa import BLOCKED_MESSAGE

    if withheld:
        outcome = "withheld"  # GROUNDING_MODE=enforce
    elif result.answer == BLOCKED_MESSAGE:
        outcome = "blocked"  # the provider's safety filter returned no text
    elif result.insufficient_evidence:
        outcome = "not_found"
    else:
        outcome = "answered"
    metrics.QUERY_ANSWERS.labels(mode=mode, outcome=outcome).inc()
    for step in result.steps:
        metrics.RAG_STAGE_LATENCY.labels(stage=step.key).observe(step.duration_ms / 1000)
    grounding = result.grounding
    if grounding is not None and outcome == "answered":
        metrics.ANSWER_GROUNDEDNESS.observe(grounding.score)
    logger.info(
        "rag_answer",
        extra={
            "mode": mode,
            "outcome": outcome,
            "model": result.model,
            "prompt_version": result.prompt_version,
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "cited_chunk_ids": _chunk_ids(result),
            "groundedness": grounding.score if grounding else None,
            "review_flags": result.injection_flags,
            "latency_ms": latency_ms,
        },
    )
    return outcome


def _chunk_ids(result: RagAnswer) -> Sequence[str]:
    return [c.chunk_id for c in result.citations]
