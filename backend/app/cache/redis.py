"""
Redis client factory.

Redis holds only rebuildable state — cache entries, rate-limit counters,
queue transport. Anything that must survive a flush lives in PostgreSQL.
Locally this is the `redis` container; in production, ElastiCache (use a
`rediss://` URL for in-transit encryption).
"""

from __future__ import annotations

from redis.asyncio import Redis

from app.core.config import Settings


def create_redis(settings: Settings) -> Redis:
    return Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=3,
        socket_timeout=5,
        health_check_interval=30,
    )


def tenant_cache_key(tenant_id: str, namespace: str, key: str) -> str:
    """Cache keys are always tenant-prefixed so a cached answer for one
    organization can never be served to another."""
    return f"ciq:{tenant_id}:{namespace}:{key}"
