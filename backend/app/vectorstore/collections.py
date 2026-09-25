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
    # Phase 6
    "level": qm.PayloadSchemaType.KEYWORD,  # child (searched) | parent (read)
    "is_current": qm.PayloadSchemaType.BOOL,  # chunk belongs to the latest version
    "embedding_model": qm.PayloadSchemaType.KEYWORD,  # never compare across models
}


class CollectionMismatchError(RuntimeError):
    """The collection's vector size differs from EMBEDDING_DIMENSION."""


async def ensure_collection(client: AsyncQdrantClient, name: str, dimension: int) -> None:
    """Create the chunk collection and payload indexes if missing. Idempotent.

    For an existing collection, only missing payload indexes are added. That
    is how collections created by an earlier release pick up fields added
    later (Phase 6 added `level`, `is_current`, `embedding_model`).
    """
    if await client.collection_exists(name):
        info = await client.get_collection(name)
        existing = set((info.payload_schema or {}).keys())
        for field, schema in PAYLOAD_INDEXES.items():
            if field not in existing:
                await client.create_payload_index(name, field_name=field, field_schema=schema)
                logger.info("qdrant_payload_index_added", extra={"field": field})
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


async def check_dimension(client: AsyncQdrantClient, name: str, dimension: int) -> None:
    """Fail with a clear message if the collection's dense vector size is not
    `dimension`, instead of an opaque Qdrant 400 on the first upsert.

    This happens when EMBEDDING_DIMENSION (or the model) is changed after
    documents were indexed. The fix is a new collection plus re-embedding —
    see docs/embeddings.md.
    """
    info = await client.get_collection(name)
    vectors = info.config.params.vectors
    size = vectors[DENSE_VECTOR].size if isinstance(vectors, dict) else None
    if size != dimension:
        raise CollectionMismatchError(
            f"Qdrant collection '{name}' stores {size}-dimensional vectors but "
            f"EMBEDDING_DIMENSION={dimension}. Use a new QDRANT_COLLECTION and re-embed."
        )
