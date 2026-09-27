"""
Erasing an organization's data everywhere it lives (Phase 22, used again by
document deletion in Phase 24).

    PostgreSQL   rows              deleted by the caller (ON DELETE CASCADE)
    Qdrant       every vector      tenant filter
    Storage      every file        tenants/<id>/ prefix (originals, parsed
                                   text, chunks, images, analysis caches)
    Redis        every cache entry  ciq:<id>:* (embeddings, captions,
                                   answers, rate limits)

Each step is idempotent, so a retried job simply finishes the work.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from qdrant_client.http import models as qm

from app.core.logging import get_logger
from app.vectorstore.qdrant import tenant_filter

if TYPE_CHECKING:
    from app.core.resources import Resources

logger = get_logger(__name__)


async def erase_tenant_data(resources: Resources, tenant_id: str) -> dict[str, Any]:
    """Remove the organization's vectors, files and cache entries."""
    await resources.qdrant.delete(
        resources.settings.qdrant_collection,
        points_selector=qm.FilterSelector(filter=tenant_filter(tenant_id)),
        wait=True,
    )
    await resources.storage.delete_prefix(f"tenants/{tenant_id}/")
    removed = await delete_redis_prefix(resources.redis, f"ciq:{tenant_id}:")
    logger.info("tenant_data_erased", extra={"tenant_id": tenant_id, "cache_keys": removed})
    return {"cache_keys": removed}


async def delete_redis_prefix(redis: Any, prefix: str) -> int:
    """Delete keys under `prefix` in batches (SCAN, never KEYS)."""
    removed, batch = 0, []
    async for key in redis.scan_iter(match=f"{prefix}*", count=500):
        batch.append(key)
        if len(batch) >= 500:
            removed += await redis.delete(*batch)
            batch = []
    if batch:
        removed += await redis.delete(*batch)
    return removed
