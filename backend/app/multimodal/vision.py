"""
Model calls for multimodal enrichment: retries, a content-hash cache, and a
concurrency limit, shared by image captioning and table summaries.

    ImageProcessor  --(PNG + prompt)-->  VisionService.ask  --> vision model
    TableProcessor  --(markdown)------>  VisionService.ask  --> same model, text only

Why a cache
-----------
Revised contracts keep most of their figures: the signature block, the
escalation diagram and the fee table of v2 are usually byte-identical to
v1. Keys hash the exact input (image bytes or table text) plus the model and
prompt version, so an unchanged figure is never paid for twice, and a new
model or prompt can never return a stale caption. Keys are tenant-scoped
like every cache key (app/cache/redis.py). Redis being down only disables
the cache (logged); it never fails a document.

Security
--------
Images and tables come from uploaded documents, i.e. untrusted input. The
prompts tell the model to describe content, never to follow instructions
found in it, and outputs are length-capped. Captions then enter the same
delimited, cited evidence path as any other contract text (Phase 7).
"""

from __future__ import annotations

import asyncio
import hashlib
import random
from collections.abc import Awaitable, Callable, Coroutine, Iterable
from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.cache.redis import tenant_cache_key
from app.core.config import Settings
from app.core.logging import get_logger
from app.llm.base import ChatMessage, LLMBlockedError, LLMConfigError, LLMError, LLMProvider

logger = get_logger(__name__)

_MAX_BACKOFF_S = 30.0


@dataclass
class MultimodalStats:
    """Reported per document in extraction_metadata["multimodal"]."""

    model: str | None = None
    images: int = 0
    images_captioned: int = 0
    images_decorative: int = 0  # logos, borders: deliberately not indexed
    images_failed: int = 0
    tables: int = 0
    tables_summarised: int = 0
    tables_failed: int = 0
    cache_hits: int = 0
    api_calls: int = 0
    retries: int = 0


class VisionService:
    def __init__(
        self,
        provider: LLMProvider,
        settings: Settings,
        redis: Redis | None = None,
        *,
        stats: MultimodalStats | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,  # tests skip real waits
    ) -> None:
        self.provider = provider
        self.redis = redis
        self.max_retries = settings.vision_max_retries
        self.cache_ttl_s = settings.caption_cache_ttl_s
        self.stats = stats or MultimodalStats()
        self.stats.model = f"{provider.name}:{provider.model}"
        self._limit = asyncio.Semaphore(max(1, settings.vision_concurrency))
        self._sleep = sleep

    async def ask(
        self,
        prompt: str,
        *,
        tenant_id: str,
        cache_tag: str,
        image: bytes | None = None,
        system: str | None = None,
        max_tokens: int = 400,
    ) -> str:
        """The model's reply to `prompt` (+ optional image), cached.

        `cache_tag` names the prompt and its version ("img-v1"): changing a
        prompt means bumping its tag so old replies are not reused.
        Raises LLMConfigError (stop: nothing else will work either) and
        LLMError / LLMBlockedError (this item failed; others may succeed).
        """
        content = image if image is not None else prompt.encode()
        key = self._cache_key(tenant_id, cache_tag, content)
        if (cached := await self._cache_get(key)) is not None:
            self.stats.cache_hits += 1
            return cached

        messages = [ChatMessage("user", prompt, images=(image,) if image is not None else ())]
        if system:
            messages.insert(0, ChatMessage("system", system))
        async with self._limit:
            text = await self._call_with_retry(messages, max_tokens)
        await self._cache_set(key, text)
        return text

    async def _call_with_retry(self, messages: list[ChatMessage], max_tokens: int) -> str:
        """Temporary errors wait 1s, 2s, 4s ... plus jitter (as in embeddings)."""
        attempt = 0
        while True:
            self.stats.api_calls += 1
            try:
                result = await self.provider.generate(messages, max_tokens=max_tokens)
                return result.text
            except (LLMConfigError, LLMBlockedError):
                raise  # a bad key or a blocked reply won't change on retry
            except LLMError:
                if attempt >= self.max_retries:
                    raise
                delay = min(2**attempt, _MAX_BACKOFF_S) + random.uniform(0, 1)  # noqa: S311
                logger.warning(
                    "vision_retry", extra={"attempt": attempt + 1, "delay_s": round(delay, 2)}
                )
                self.stats.retries += 1
                attempt += 1
                await self._sleep(delay)

    # --- cache ---------------------------------------------------------------------

    def _cache_key(self, tenant_id: str, cache_tag: str, content: bytes) -> str:
        digest = hashlib.sha256(content).hexdigest()
        model = f"{self.provider.name}:{self.provider.model}"
        return tenant_cache_key(tenant_id, "mm", f"{model}:{cache_tag}:{digest}")

    async def _cache_get(self, key: str) -> str | None:
        if not self.redis or not self.cache_ttl_s:
            return None
        try:
            value = await self.redis.get(key)
        except RedisError as exc:
            logger.warning("caption_cache_unavailable", extra={"error": repr(exc)})
            return None
        return value if isinstance(value, str) else None

    async def _cache_set(self, key: str, text: str) -> None:
        if not self.redis or not self.cache_ttl_s:
            return
        try:
            await self.redis.set(key, text, ex=self.cache_ttl_s)
        except RedisError as exc:
            logger.warning("caption_cache_unavailable", extra={"error": repr(exc)})


async def run_all(coros: Iterable[Coroutine[Any, Any, None]]) -> None:
    """Run coroutines concurrently; the first error cancels the rest and is
    re-raised as itself (not wrapped in an ExceptionGroup), so callers can
    catch e.g. LLMConfigError normally."""
    try:
        async with asyncio.TaskGroup() as group:
            for coro in coros:
                group.create_task(coro)
    except BaseExceptionGroup as errors:
        raise errors.exceptions[0] from None


def clean_reply(text: str, *, max_chars: int) -> str:
    """One tidy paragraph: models sometimes wrap replies in quotes or code
    fences, and a runaway reply must not become a 5,000-character chunk."""
    text = text.strip().strip("`").strip()
    text = " ".join(text.split())
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0] + " …"
    return text
