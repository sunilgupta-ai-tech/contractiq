"""
Hybrid search in Qdrant: dense (meaning) + sparse (keywords), fused with RRF.

Why hybrid
----------
Questions about contracts mix both kinds of need:
  "Can we end the deal early?"          -> meaning   (dense finds "terminate")
  "What does clause 8.3 say?"            -> exact term (sparse finds "8.3")
  "Is the £5,000,000 cap mutual?"        -> both
Either search alone misses one kind. Running both and fusing the rankings
gets the best of each.

How fusion works (Reciprocal Rank Fusion)
-----------------------------------------
Each search returns a ranked list. RRF scores a chunk by
sum(1 / (k + rank)) over the lists it appears in. It uses only *ranks*, so
the two searches' incompatible score scales (cosine vs BM25) never need to
be normalised against each other. Qdrant does this server-side in one call
(`prefetch` both searches, then `FusionQuery(RRF)`).

The filter
----------
Every search is restricted, inside Qdrant, to:
  * the caller's tenant           (tenant_filter — cannot be removed)
  * child chunks                  (parents have no vectors anyway)
  * the current embedding model   (never compare vectors across models)
  * latest versions only, unless specific versions are requested
  * the selected documents, if any
"""

from __future__ import annotations

from collections.abc import Sequence

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qm

from app.rag.types import RetrievedChunk
from app.vectorstore.collections import DENSE_VECTOR, SPARSE_VECTOR
from app.vectorstore.qdrant import tenant_filter
from app.vectorstore.sparse import SparseVector


def retrieval_filter(
    tenant_id: str,
    *,
    embedding_model: str,
    document_ids: Sequence[str] | None = None,
    version_ids: Sequence[str] | None = None,
) -> qm.Filter:
    """The filter every question-answering search uses (see module docstring)."""
    extra: list[qm.Condition] = [
        qm.FieldCondition(key="level", match=qm.MatchValue(value="child")),
        qm.FieldCondition(key="embedding_model", match=qm.MatchValue(value=embedding_model)),
    ]
    if not version_ids:
        # Without explicit versions, answer from each document's latest version.
        extra.append(qm.FieldCondition(key="is_current", match=qm.MatchValue(value=True)))
    return tenant_filter(tenant_id, document_ids=document_ids, version_ids=version_ids, extra=extra)


async def hybrid_search(
    client: AsyncQdrantClient,
    collection: str,
    *,
    dense: list[float],
    sparse: SparseVector,
    query_filter: qm.Filter,
    prefetch: int,
    limit: int,
) -> list[RetrievedChunk]:
    """One Qdrant call: dense top-`prefetch` + sparse top-`prefetch`, RRF-fused
    to `limit` results. The filter is applied inside each prefetch, so no
    out-of-scope chunk can even enter the candidate lists."""
    searches = [
        qm.Prefetch(query=dense, using=DENSE_VECTOR, filter=query_filter, limit=prefetch),
    ]
    if sparse.indices:  # a question of only stopwords has no keyword part
        searches.append(
            qm.Prefetch(
                query=qm.SparseVector(indices=sparse.indices, values=sparse.values),
                using=SPARSE_VECTOR,
                filter=query_filter,
                limit=prefetch,
            )
        )
    response = await client.query_points(
        collection,
        prefetch=searches,
        query=qm.FusionQuery(fusion=qm.Fusion.RRF),
        query_filter=query_filter,
        limit=limit,
        with_payload=True,
    )
    return [
        RetrievedChunk.from_payload(dict(point.payload or {}), point.score)
        for point in response.points
        if point.payload
    ]
