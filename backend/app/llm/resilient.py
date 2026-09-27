"""
Resilient model calls (Phase 21): retry, fallback model, circuit breaker.

    caller -> ResilientLLM -> primary model   (retried on 429 / 5xx / timeout)
                          \\-> fallback model  (after retries, or while the
                                               primary's circuit is open)

* Retry: temporary errors (LLMError) are retried with exponential backoff
  and jitter. Configuration errors (bad key, unknown model) and blocked
  replies (safety filter) are not — retrying cannot help.
* Fallback: if the primary still fails, one call to a second model
  (LLM_FALLBACK_MODEL, e.g. a lighter/cheaper one or another provider).
* Circuit breaker: after LLM_BREAKER_THRESHOLD consecutive failures the
  primary is not called for LLM_BREAKER_COOLDOWN_S seconds; requests go to
  the fallback, or fail fast with a clear 503 instead of every user waiting
  for timeouts. The next call after the cooldown is a trial ("half-open"):
  success closes the circuit, failure opens it again.

One breaker per process and model; in a fleet, each instance protects
itself, which is what matters for latency.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable

from app.core.logging import get_logger
from app.llm.base import (
    ChatMessage,
    LLMBlockedError,
    LLMConfigError,
    LLMError,
    LLMProvider,
    LLMResult,
)

logger = get_logger(__name__)

_MAX_BACKOFF_S = 8.0


class CircuitOpenError(LLMError):
    """The model is failing repeatedly; calls are paused for a moment."""


class CircuitBreaker:
    def __init__(
        self, *, threshold: int, cooldown_s: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.threshold = max(1, threshold)
        self.cooldown_s = cooldown_s
        self._clock = clock
        self._failures = 0
        self._opened_at: float | None = None

    @property
    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if self._clock() - self._opened_at >= self.cooldown_s:
            return False  # half-open: let one trial call through
        return True

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.threshold:
            if self._opened_at is None or not self.is_open:
                logger.warning("llm_circuit_open", extra={"failures": self._failures})
            self._opened_at = self._clock()


class ResilientLLM:
    def __init__(
        self,
        primary: LLMProvider,
        *,
        fallback: LLMProvider | None = None,
        max_retries: int = 2,
        breaker: CircuitBreaker | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.max_retries = max(0, max_retries)
        self.breaker = breaker or CircuitBreaker(threshold=5, cooldown_s=30.0)
        self._sleep = sleep

    @property
    def name(self) -> str:
        return self.primary.name

    @property
    def model(self) -> str:
        return self.primary.model

    async def generate(
        self, messages: list[ChatMessage], *, temperature: float = 0.0, max_tokens: int = 1024
    ) -> LLMResult:
        if self.breaker.is_open:
            return await self._fallback_or_raise(
                messages,
                temperature,
                max_tokens,
                CircuitOpenError("The model is busy; try again shortly."),
            )
        attempt = 0
        while True:
            try:
                result = await self.primary.generate(
                    messages, temperature=temperature, max_tokens=max_tokens
                )
            except (LLMConfigError, LLMBlockedError):
                raise
            except LLMError as exc:
                self.breaker.record_failure()
                if attempt >= self.max_retries or self.breaker.is_open:
                    return await self._fallback_or_raise(messages, temperature, max_tokens, exc)
                delay = min(_MAX_BACKOFF_S, 0.5 * 2**attempt) + random.uniform(0, 0.25)  # noqa: S311
                logger.info("llm_retry", extra={"attempt": attempt + 1, "delay_s": round(delay, 2)})
                attempt += 1
                await self._sleep(delay)
                continue
            self.breaker.record_success()
            return result

    async def _fallback_or_raise(
        self, messages: list[ChatMessage], temperature: float, max_tokens: int, error: LLMError
    ) -> LLMResult:
        if self.fallback is None:
            raise error
        logger.warning(
            "llm_fallback",
            extra={
                "primary": self.primary.model,
                "fallback": self.fallback.model,
                "error": str(error),
            },
        )
        return await self.fallback.generate(
            messages, temperature=temperature, max_tokens=max_tokens
        )

    async def aclose(self) -> None:
        await self.primary.aclose()
        if self.fallback is not None:
            await self.fallback.aclose()
