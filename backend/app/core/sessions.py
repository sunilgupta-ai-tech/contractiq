"""
Immediate revocation of access tokens (Phase 17).

Access tokens carry the user's permissions, so authorization needs no
database read. The price is staleness: a token issued before a user's role
changed would keep the old permissions until it expires. To avoid that, a
change records "tokens issued before now are stale" in Redis:

    ciq:auth:valid-after:user:<user id>   role changed, user deactivated
    ciq:auth:valid-after:org:<tenant id>  a role's permissions changed,
                                          organization suspended (Phase 18)

Every request compares its token's `ts` with both markers (one MGET). A
stale token gets 401; the frontend then refreshes silently, and refresh
re-reads the user, role and organization from the database, so the new
token carries the current permissions, or refresh is refused.

Markers expire with the longest-lived access token they could affect. If
Redis is unreachable the check is skipped (and logged): refresh still
re-reads the database, so a change still applies within one access-token
lifetime, and the API stays up.
"""

from __future__ import annotations

import time
import uuid

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.logging import get_logger

logger = get_logger(__name__)


def _user_key(user_id: uuid.UUID | str) -> str:
    return f"ciq:auth:valid-after:user:{user_id}"


def _org_key(tenant_id: uuid.UUID | str) -> str:
    return f"ciq:auth:valid-after:org:{tenant_id}"


def _now_ms() -> int:
    return int(time.time() * 1000)


async def _mark(redis: Redis | None, key: str, ttl_s: int) -> None:
    if redis is None:
        return
    try:
        await redis.set(key, _now_ms(), ex=max(ttl_s, 60))
    except RedisError as exc:
        logger.warning("session_revoke_failed", extra={"key": key, "error": repr(exc)})


async def revoke_user_sessions(redis: Redis | None, user_id: uuid.UUID, *, ttl_s: int) -> None:
    """The user's current access tokens stop working; they refresh (or not)."""
    await _mark(redis, _user_key(user_id), ttl_s)


async def revoke_org_sessions(redis: Redis | None, tenant_id: uuid.UUID, *, ttl_s: int) -> None:
    """Every access token of the organization stops working."""
    await _mark(redis, _org_key(tenant_id), ttl_s)


async def token_is_current(redis: Redis | None, *, user_id: str, tenant_id: str, ts: int) -> bool:
    if redis is None:
        return True
    try:
        user_mark, org_mark = await redis.mget(_user_key(user_id), _org_key(tenant_id))
    except RedisError as exc:
        logger.warning("session_check_skipped", extra={"error": repr(exc)})
        return True
    return all(mark is None or ts > int(mark) for mark in (user_mark, org_mark))


# --- Platform console (Phase 18) ----------------------------------------------------


def _platform_key(admin_id: uuid.UUID | str) -> str:
    return f"ciq:auth:valid-after:platform:{admin_id}"


async def revoke_platform_sessions(redis: Redis | None, admin_id: uuid.UUID, *, ttl_s: int) -> None:
    await _mark(redis, _platform_key(admin_id), ttl_s)


async def platform_token_is_current(redis: Redis | None, *, admin_id: str, ts: int) -> bool:
    if redis is None:
        return True
    try:
        mark = await redis.get(_platform_key(admin_id))
    except RedisError as exc:
        logger.warning("session_check_skipped", extra={"error": repr(exc)})
        return True
    return mark is None or ts > int(mark)
