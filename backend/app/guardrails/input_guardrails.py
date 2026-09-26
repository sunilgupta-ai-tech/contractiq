"""
Input guardrails (Phase 11): clean text before it reaches search or a model,
and rate-limit the endpoints that cost money or invite brute force.

Text hygiene
------------
`clean_text` normalises Unicode (NFKC: full-width letters and ligatures
become plain ones, so filters and keyword search see ordinary text) and
removes invisible characters: zero-width spaces/joiners, bidirectional
overrides and other control characters. These are how instructions are
hidden from a human reviewer while a model still reads them ("ASCII
smuggling"), and they break keyword matching. Length limits stay in the
request schemas.

Rate limiting
-------------
Fixed-window counters in Redis (INCR + EXPIRE, one round trip):

    query       per user and per tenant   (model + embedding cost)
    analysis    per user                  (up to ~16 model calls each)
    upload      per user                  (OCR/VLM processing cost)
    login       failed attempts per (IP, email) and per IP  (brute force)

Keys are tenant-prefixed where a tenant is known; login keys hash the email,
so no address is stored in Redis. A limit that is hit returns 429 with
`Retry-After`.

If Redis is unavailable the limiter *fails open* (logged): a cache outage
must not take down question answering or sign-in. Login still pays the
bcrypt cost per attempt, which is itself a throttle. With no infrastructure
at all (unit tests that don't start the app), limiting is skipped.
"""

from __future__ import annotations

import hashlib
import re
import time
import unicodedata
from dataclasses import dataclass

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.cache.redis import tenant_cache_key
from app.core.config import Settings
from app.core.exceptions import RateLimitedError
from app.core.logging import get_logger

logger = get_logger(__name__)

# Zero-width characters, bidi embeddings/overrides/isolates, BOM, word joiner.
_INVISIBLE = re.compile("[​-‏‪-‮⁠-⁤⁦-⁩﻿]")
_BLANK_LINES = re.compile(r"\n{3,}")


def clean_text(text: str) -> str:
    """NFKC-normalised text without invisible or control characters (newlines
    and tabs kept), with runs of blank lines collapsed and ends trimmed."""
    text = _INVISIBLE.sub("", unicodedata.normalize("NFKC", text))
    text = "".join(
        ch for ch in text if ch in "\n\t" or unicodedata.category(ch) not in ("Cc", "Cf", "Co")
    )
    return _BLANK_LINES.sub("\n\n", text).strip()


@dataclass(frozen=True)
class Limit:
    name: str
    max_requests: int
    window_s: int


class RateLimiter:
    def __init__(self, redis: Redis | None, *, enabled: bool = True) -> None:
        self.redis = redis
        self.enabled = enabled and redis is not None

    async def hit(self, limit: Limit, subject: str, *, tenant_id: str | None = None) -> None:
        """Count one request; raise RateLimitedError once over the limit."""
        count, retry_after = await self._incr(limit, subject, tenant_id)
        if count > limit.max_requests:
            logger.warning("rate_limited", extra={"limit": limit.name})
            raise _limited(retry_after)

    async def check(self, limit: Limit, subject: str, *, tenant_id: str | None = None) -> None:
        """Raise if the limit is already reached, without counting (used for
        login, where only *failed* attempts are counted)."""
        if not self.enabled:
            return
        key, retry_after = self._key(limit, subject, tenant_id)
        try:
            raw = await self.redis.get(key)  # type: ignore[union-attr]
        except RedisError as exc:
            logger.warning("rate_limit_unavailable", extra={"error": type(exc).__name__})
            return
        if raw is not None and int(raw) >= limit.max_requests:
            logger.warning("rate_limited", extra={"limit": limit.name})
            raise _limited(retry_after)

    async def record(self, limit: Limit, subject: str, *, tenant_id: str | None = None) -> None:
        """Count one event without enforcing (e.g. a failed login)."""
        await self._incr(limit, subject, tenant_id)

    async def reset(self, limit: Limit, subject: str, *, tenant_id: str | None = None) -> None:
        if not self.enabled:
            return
        key, _ = self._key(limit, subject, tenant_id)
        try:
            await self.redis.delete(key)  # type: ignore[union-attr]
        except RedisError as exc:
            logger.warning("rate_limit_unavailable", extra={"error": type(exc).__name__})

    async def _incr(self, limit: Limit, subject: str, tenant_id: str | None) -> tuple[int, int]:
        if not self.enabled:
            return 0, 0
        key, retry_after = self._key(limit, subject, tenant_id)
        try:
            async with self.redis.pipeline(transaction=True) as pipe:  # type: ignore[union-attr]
                pipe.incr(key)
                pipe.expire(key, limit.window_s + 1)
                count, _ = await pipe.execute()
        except RedisError as exc:
            logger.warning("rate_limit_unavailable", extra={"error": type(exc).__name__})
            return 0, 0
        return int(count), retry_after

    @staticmethod
    def _key(limit: Limit, subject: str, tenant_id: str | None) -> tuple[str, int]:
        now = int(time.time())
        window = now // limit.window_s
        retry_after = limit.window_s - now % limit.window_s
        name = f"{limit.name}:{subject}:{window}"
        if tenant_id is not None:
            return tenant_cache_key(tenant_id, "rl", name), retry_after
        return f"ciq:global:rl:{name}", retry_after


def subject_hash(*parts: str) -> str:
    """A stable, non-reversible key part (e.g. IP + email for login limits)."""
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]


def _limited(retry_after: int) -> RateLimitedError:
    return RateLimitedError(
        details={"retry_after_s": retry_after}, headers={"Retry-After": str(retry_after)}
    )


def limits_for(kind: str, *, settings: Settings) -> list[tuple[Limit, bool]]:
    """(limit, per_tenant) pairs for a kind of request. per_tenant=False means
    the subject is the user; True means the whole organization."""
    minute = 60
    if kind == "query":
        return [
            (Limit("query_user", settings.rate_limit_query_per_minute, minute), False),
            (Limit("query_tenant", settings.rate_limit_query_tenant_per_minute, minute), True),
        ]
    if kind == "analysis":
        return [(Limit("analysis_user", settings.rate_limit_analysis_per_minute, minute), False)]
    if kind == "upload":
        return [(Limit("upload_user", settings.rate_limit_upload_per_minute, minute), False)]
    raise ValueError(f"unknown rate-limit kind {kind!r}")


def login_limits(settings: Settings) -> tuple[Limit, Limit]:
    """(per IP + email, per IP) failed-login limits."""
    return (
        Limit("login_fail", settings.login_max_failures, settings.login_window_s),
        Limit("login_fail_ip", settings.login_max_failures_per_ip, settings.login_window_s),
    )
