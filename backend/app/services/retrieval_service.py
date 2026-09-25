"""
Tenant-scoped hybrid retrieval — the production `Retriever`.

    question
      ├─ EmbeddingService.embed_query()   dense vector (RETRIEVAL_QUERY task, cached)
      ├─ sparse_vector(query=True)        keyword vector (same hashing as indexing)
      └─ hybrid_search()                  one Qdrant call, RRF-fused, filtered by
                                          retrieval_filter() (tenant always included)

Parents (whole sections) are fetched by id for small-to-big context; the
tenant is re-checked on every returned point (see vectorstore.indexing).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from app.llm.base import embedding_model_label
from app.rag.hybrid_search import hybrid_search, retrieval_filter
from app.rag.types import RetrievedChunk
from app.services.embedding_service import EmbeddingService
from app.vectorstore.indexing import get_parents
from app.vectorstore.sparse import sparse_vector

if TYPE_CHECKING:
    from app.core.resources import Resources


class RetrievalService:
    def __init__(self, resources: Resources) -> None:
        self.resources = resources
        self.settings = resources.settings

    async def retrieve(
        self,
        question: str,
        *,
        tenant_id: str,
        document_ids: Sequence[str] | None,
        version_ids: Sequence[str] | None,
        limit: int,
    ) -> list[RetrievedChunk]:
        provider = self.resources.embeddings()
        embedder = EmbeddingService(provider, self.settings, self.resources.redis)
        dense = await embedder.embed_query(question, tenant_id=tenant_id)
        return await hybrid_search(
            self.resources.qdrant,
            self.settings.qdrant_collection,
            dense=dense,
            sparse=sparse_vector(question, query=True),
            query_filter=retrieval_filter(
                tenant_id,
                # Only points embedded with the model we just used are comparable.
                embedding_model=embedding_model_label(provider),
                document_ids=document_ids,
                version_ids=version_ids,
            ),
            prefetch=self.settings.retrieval_prefetch,
            limit=limit,
        )

    async def parents(self, *, tenant_id: str, parent_ids: Sequence[str]) -> dict[str, Any]:
        payloads = await get_parents(
            self.resources.qdrant,
            self.settings.qdrant_collection,
            tenant_id=tenant_id,
            parent_ids=list(dict.fromkeys(parent_ids)),
        )
        return {p["chunk_id"]: p for p in payloads}
