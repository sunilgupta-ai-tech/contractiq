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
from app.storage import document_prefix
from app.vectorstore.indexing import delete_document_points
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


# Cache namespaces holding content derived from documents: answers (text),
# captions and table summaries (text), embeddings (vectors). Entries are
# keyed by content hash, not by document, so a document's deletion clears
# the organization's whole namespace: the price is paying again for a few
# captions or embeddings later, never keeping a deleted document's content.
DOCUMENT_DERIVED_CACHES = ("answer", "mm", "emb")


async def erase_document_data(
    resources: Resources, tenant_id: str, document_id: str
) -> dict[str, Any]:
    """Phase 24: everything derived from one deleted document, outside
    PostgreSQL. Idempotent; run by the worker after the rows are gone."""
    await delete_document_points(
        resources.qdrant,
        resources.settings.qdrant_collection,
        tenant_id=tenant_id,
        document_id=document_id,
    )
    await resources.storage.delete_prefix(document_prefix(tenant_id, document_id))
    removed = 0
    for namespace in DOCUMENT_DERIVED_CACHES:
        removed += await delete_redis_prefix(resources.redis, f"ciq:{tenant_id}:{namespace}:")
    logger.info(
        "document_data_erased",
        extra={"tenant_id": tenant_id, "document_id": document_id, "cache_keys": removed},
    )
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
