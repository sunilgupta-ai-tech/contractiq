"""
Qdrant client factory and tenant-safe filter construction.

Locally this is the `qdrant` container; in production, Qdrant Cloud or a
self-hosted cluster (set QDRANT_URL + QDRANT_API_KEY). The client is async
so vector search never blocks the event loop.
"""

from __future__ import annotations

from collections.abc import Sequence

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qm

from app.core.config import Settings


def create_qdrant(settings: Settings) -> AsyncQdrantClient:
    api_key = settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None
    return AsyncQdrantClient(url=settings.qdrant_url, api_key=api_key, timeout=10)


def tenant_filter(
    tenant_id: str,
    *,
    document_ids: Sequence[str] | None = None,
    version_ids: Sequence[str] | None = None,
    extra: Sequence[qm.Condition] = (),
) -> qm.Filter:
    """Build the mandatory retrieval filter.

    Every vector query must go through this function. The tenant condition
    is always the first `must` clause and cannot be removed by callers, so
    Organization A can never retrieve Organization B's chunks — regardless
    of what the user or the LLM asks for.
    """
    must: list[qm.Condition] = [
        qm.FieldCondition(key="tenant_id", match=qm.MatchValue(value=tenant_id))
    ]
    if document_ids:
        must.append(qm.FieldCondition(key="document_id", match=qm.MatchAny(any=list(document_ids))))
    if version_ids:
        must.append(qm.FieldCondition(key="version_id", match=qm.MatchAny(any=list(version_ids))))
    must.extend(extra)
    return qm.Filter(must=must)
