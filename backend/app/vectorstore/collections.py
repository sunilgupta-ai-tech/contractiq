"""
Qdrant collection schema.

A single collection holds every tenant's chunks, partitioned by a
`tenant_id` payload index (Qdrant's recommended multitenancy pattern —
far cheaper than one collection per tenant).

Each point carries two named vectors:
  * `dense`  — semantic embedding (cosine)
  * `sparse` — BM25-style lexical vector for hybrid search (Phase 7)
so hybrid retrieval is a single Qdrant query with server-side fusion.
"""

from __future__ import annotations

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qm

from app.core.logging import get_logger

logger = get_logger(__name__)

DENSE_VECTOR = "dense"
SPARSE_VECTOR = "sparse"

# Payload fields that are filtered on and therefore indexed.
PAYLOAD_INDEXES: dict[str, qm.PayloadSchemaType] = {
    "document_id": qm.PayloadSchemaType.KEYWORD,
    "version_id": qm.PayloadSchemaType.KEYWORD,
    "contract_type": qm.PayloadSchemaType.KEYWORD,
    "section": qm.PayloadSchemaType.KEYWORD,
    "clause": qm.PayloadSchemaType.KEYWORD,
    "chunk_type": qm.PayloadSchemaType.KEYWORD,  # text | table | image_caption
    "page": qm.PayloadSchemaType.INTEGER,
}


async def ensure_collection(client: AsyncQdrantClient, name: str, dimension: int) -> None:
    """Create the chunk collection and payload indexes if missing. Idempotent."""
    if await client.collection_exists(name):
        return

    await client.create_collection(
        collection_name=name,
        vectors_config={DENSE_VECTOR: qm.VectorParams(size=dimension, distance=qm.Distance.COSINE)},
        sparse_vectors_config={SPARSE_VECTOR: qm.SparseVectorParams(modifier=qm.Modifier.IDF)},
        # Store vectors on disk; keep HNSW graph in RAM. Good default for
        # contract corpora that outgrow memory.
        on_disk_payload=True,
    )
    # `is_tenant=True` lets Qdrant co-locate each tenant's points.
    await client.create_payload_index(
        name,
        field_name="tenant_id",
        field_schema=qm.KeywordIndexParams(type=qm.KeywordIndexType.KEYWORD, is_tenant=True),
    )
    for field, schema in PAYLOAD_INDEXES.items():
        await client.create_payload_index(name, field_name=field, field_schema=schema)
    logger.info("qdrant_collection_created", extra={"collection": name, "dimension": dimension})
