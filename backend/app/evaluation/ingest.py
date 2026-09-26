"""
Index a golden-dataset contract the way the worker would (Phase 12).

    parse -> OCR -> layout -> chunk -> embed -> index (+ mark current)

Uses the same service functions as workers/app/services/pipeline.py, in the
same order; the worker's stage wrapper (status updates, parsed.json/images
in storage) is not needed here. Multimodal captioning is skipped: the
golden set asks about text and tables, and captions would add vision-model
cost and variance to every evaluation run.

Everything lands in the run's own Qdrant collection under a throwaway
tenant id, so an evaluation never touches real tenants' data.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from qdrant_client import AsyncQdrantClient
from redis.asyncio import Redis

from app.chunking.models import Chunk
from app.core.config import Settings
from app.llm.base import EmbeddingProvider, embedding_model_label
from app.services.chunking_service import CHUNKER_VERSION, ChunkingOptions, chunk_document
from app.services.embedding_service import EmbeddingService
from app.services.ocr_service import ocr_scanned_pages
from app.services.pdf_service import PdfOptions, finalize_layout, parse_pdf
from app.vectorstore.collections import ensure_collection
from app.vectorstore.indexing import IndexTarget, build_points, mark_current_version, upsert_version


@dataclass
class IngestedDocument:
    key: str
    document_id: str
    version_id: str
    children: list[Chunk]  # the searchable chunks: used to find every relevant chunk
    page_count: int


async def ingest_document(
    pdf: bytes,
    *,
    key: str,
    title: str,
    contract_type: str,
    tenant_id: str,
    document_id: str,
    version_id: str,
    settings: Settings,
    embeddings: EmbeddingProvider,
    qdrant: AsyncQdrantClient,
    redis: Redis | None,
) -> IngestedDocument:
    options = PdfOptions.from_settings(settings)
    parsed = await asyncio.to_thread(parse_pdf, pdf, options)
    parsed.images.clear()  # no captioning in evaluation runs (see module docstring)
    await asyncio.to_thread(ocr_scanned_pages, pdf, parsed.document, options)
    finalize_layout(parsed.document)

    chunks = await asyncio.to_thread(
        chunk_document,
        parsed.document,
        version_id=version_id,
        document_title=title,
        options=ChunkingOptions.from_settings(settings),
    )
    service = EmbeddingService(embeddings, settings, redis)
    vectors, _ = await service.embed_documents(
        [c.embedding_text for c in chunks.children], tenant_id=tenant_id
    )

    collection = settings.qdrant_collection
    await ensure_collection(qdrant, collection, settings.embedding_dimension)
    target = IndexTarget(
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
        version_label="v1",
        document_title=title,
        contract_type=contract_type,
        is_current=True,
        embedding_model=embedding_model_label(embeddings),
        chunker_version=CHUNKER_VERSION,
    )
    points = build_points(chunks.children, vectors, chunks.parents, target)
    await upsert_version(qdrant, collection, target, points)
    await mark_current_version(
        qdrant, collection, tenant_id=tenant_id, document_id=document_id, version_id=version_id
    )
    return IngestedDocument(
        key=key,
        document_id=document_id,
        version_id=version_id,
        children=chunks.children,
        page_count=parsed.document.page_count,
    )
