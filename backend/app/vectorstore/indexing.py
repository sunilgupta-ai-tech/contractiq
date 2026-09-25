"""
Writing chunks to Qdrant, and keeping the index consistent.

One point per chunk, id = chunk.id (deterministic, from Phase 5):

    CHILD  point  vectors: dense (embedding) + sparse (keywords)   -> searched
    PARENT point  no vectors                                        -> fetched by id

Parents live in the same collection as their children (payload
`level="parent"`) so that a search hit can be expanded to its section with
one `retrieve` call and the same tenant check. With no vectors, a parent can
never be returned by a similarity search.

Every point's payload carries `tenant_id`; all reads and deletes here go
through `tenant_filter()` or re-check the tenant on the returned points.

Re-indexing without a search gap
--------------------------------
A version is re-indexed by upserting the new points first, then deleting
that version's points whose ids are no longer present. Because ids are
deterministic, unchanged chunks are simply overwritten in place, and at no
moment does the version disappear from search.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qm

from app.chunking.models import Chunk, ChunkLevel
from app.vectorstore.collections import DENSE_VECTOR, SPARSE_VECTOR
from app.vectorstore.qdrant import tenant_filter
from app.vectorstore.sparse import sparse_vector

UPSERT_BATCH = 256  # points per request: large enough to be fast, small enough for 32 MB limits


@dataclass(frozen=True)
class IndexTarget:
    """Document-level facts copied into every point's payload, so a search
    hit carries everything needed for filtering and citing without a DB call."""

    tenant_id: str
    document_id: str
    version_id: str
    version_label: str
    document_title: str | None
    contract_type: str
    is_current: bool  # this version is the document's latest
    embedding_model: str  # "<provider>:<model>:<dimension>"
    chunker_version: int


def chunk_payload(chunk: Chunk, target: IndexTarget) -> dict[str, Any]:
    return {
        # identity & tenancy
        "tenant_id": target.tenant_id,
        "document_id": target.document_id,
        "version_id": target.version_id,
        "version_label": target.version_label,
        "chunk_id": chunk.id,
        "parent_id": chunk.parent_id,
        "level": chunk.level.value,
        "chunk_type": chunk.chunk_type.value,
        # document facts (filters + display)
        "document_title": target.document_title,
        "contract_type": target.contract_type,
        "is_current": target.is_current,
        # structure (filters + citations)
        "section": chunk.section,
        "section_title": chunk.section_title,
        "clause": chunk.clause,
        "clause_title": chunk.clause_title,
        "clauses": chunk.clauses,
        "heading_path": chunk.heading_path,
        "page": chunk.page_start,
        "page_end": chunk.page_end,
        "regions": [{"page": r.page, "bbox": list(r.bbox)} for r in chunk.regions],
        # content
        "text": chunk.text,
        "token_count": chunk.token_count,
        # provenance: which model/rules produced this point
        "embedding_model": target.embedding_model,
        "chunker_version": target.chunker_version,
    }


def build_points(
    children: Sequence[Chunk],
    vectors: Sequence[list[float]],
    parents: Sequence[Chunk],
    target: IndexTarget,
) -> list[qm.PointStruct]:
    if len(children) != len(vectors):
        raise ValueError(f"{len(children)} child chunks but {len(vectors)} vectors")
    points = []
    for chunk, vector in zip(children, vectors, strict=True):
        sparse = sparse_vector(chunk.embedding_text)
        points.append(
            qm.PointStruct(
                id=chunk.id,
                vector={
                    DENSE_VECTOR: vector,
                    SPARSE_VECTOR: qm.SparseVector(indices=sparse.indices, values=sparse.values),
                },
                payload=chunk_payload(chunk, target),
            )
        )
    for parent in parents:
        points.append(
            qm.PointStruct(id=parent.id, vector={}, payload=chunk_payload(parent, target))
        )
    return points


async def upsert_version(
    client: AsyncQdrantClient, collection: str, target: IndexTarget, points: list[qm.PointStruct]
) -> int:
    """Write a version's points, then remove its stale ones. Returns the
    number of points written. `wait=True` so the job only completes once the
    points are actually searchable."""
    for start in range(0, len(points), UPSERT_BATCH):
        await client.upsert(collection, points=points[start : start + UPSERT_BATCH], wait=True)

    scope = tenant_filter(target.tenant_id, version_ids=[target.version_id])
    keep: list[qm.ExtendedPointId] = [p.id for p in points]
    await client.delete(
        collection,
        points_selector=qm.FilterSelector(
            filter=qm.Filter(must=scope.must, must_not=[qm.HasIdCondition(has_id=keep)])
        ),
        wait=True,
    )
    return len(points)


async def mark_current_version(
    client: AsyncQdrantClient, collection: str, *, tenant_id: str, document_id: str, version_id: str
) -> None:
    """Make `version_id` the document's searchable-by-default version.

    Older versions stay indexed (version comparison needs them) but are
    flagged `is_current=False`, so ordinary search ignores them. The new
    version is flagged first, so there is a brief overlap rather than a
    moment where the document has no current version.
    """
    this_version = tenant_filter(tenant_id, document_ids=[document_id], version_ids=[version_id])
    await client.set_payload(
        collection, payload={"is_current": True}, points=this_version, wait=True
    )
    document = tenant_filter(tenant_id, document_ids=[document_id])
    others = qm.Filter(
        must=document.must,
        must_not=[qm.FieldCondition(key="version_id", match=qm.MatchValue(value=version_id))],
    )
    await client.set_payload(collection, payload={"is_current": False}, points=others, wait=True)


async def delete_document_points(
    client: AsyncQdrantClient, collection: str, *, tenant_id: str, document_id: str
) -> None:
    await client.delete(
        collection,
        points_selector=qm.FilterSelector(
            filter=tenant_filter(tenant_id, document_ids=[document_id])
        ),
        wait=True,
    )


async def get_parents(
    client: AsyncQdrantClient, collection: str, *, tenant_id: str, parent_ids: Sequence[str]
) -> list[dict[str, Any]]:
    """Payloads of parent chunks by id (small-to-big expansion, Phase 7).

    Retrieval by id bypasses filters, so the tenant is re-checked on every
    returned point: an id from another tenant yields nothing.
    """
    if not parent_ids:
        return []
    records = await client.retrieve(collection, ids=list(parent_ids), with_payload=True)
    return [
        dict(r.payload)
        for r in records
        if r.payload
        and r.payload.get("tenant_id") == tenant_id
        and r.payload.get("level") == ChunkLevel.PARENT.value
    ]
