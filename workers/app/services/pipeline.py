"""
Document ingestion pipeline definition.

The pipeline is an ordered list of stages. Each stage maps to a
`DocumentStatus`, so the status the user sees in the UI is exactly the
stage the worker is executing. Stage handlers are filled in phase by phase:

    parse  (Phase 4)  PDF text layer, tables, images      -> artifacts["parse"]
    ocr    (Phase 4)  OCR scanned pages, layout, save JSON -> artifacts["parsed"]
    chunk  (Phase 5)  section/clause-aware chunks, save JSON -> artifacts["chunks"]
    embed  (Phase 6)  embeddings (Gemini by default), with cache  -> artifacts["vectors"]
    index  (Phase 6)  Qdrant upsert + prune, current-version flag

Stages communicate only through `StageContext`: `artifacts` carries data to
the next stage in memory, and `version_updates` collects fields that
`process_document` writes to the DocumentVersion row when the run ends.
Stage handlers never touch the database themselves, which keeps them easy
to test and keeps every DB write in one place (the task).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from app.chunking.models import Chunk
from app.db.models import DocumentStatus
from app.document_processing.parser import ParsedDocument
from app.document_processing.pymupdf_parser import to_page_image
from app.llm.base import embedding_model_label
from app.services.chunking_service import (
    CHUNKER_VERSION,
    ChunkingOptions,
    ChunkingResult,
    chunk_document,
)
from app.services.embedding_service import EmbeddingService
from app.services.ocr_service import ocr_scanned_pages
from app.services.pdf_service import (
    ParseResult,
    PdfOptions,
    extraction_summary,
    finalize_layout,
    parse_pdf,
)
from app.storage import build_object_key
from app.vectorstore.collections import check_dimension
from app.vectorstore.indexing import (
    IndexTarget,
    build_points,
    mark_current_version,
    upsert_version,
)

StageHandler = Callable[["StageContext"], Awaitable[None]]


@dataclass
class StageContext:
    """Mutable state handed from stage to stage for one document version."""

    tenant_id: str
    document_id: str
    version_id: str
    storage_key: str  # where the original PDF is stored
    resources: Any
    # The title the user gave the document; used as the root of every
    # chunk's heading path ("Master Services Agreement > 8. Termination").
    document_title: str | None = None
    # Copied into every Qdrant point's payload (Phase 6).
    version_label: str = "v1"
    contract_type: str = "OTHER"
    is_latest_version: bool = True
    artifacts: dict[str, Any] = field(default_factory=dict)
    # Column name -> value, applied to the DocumentVersion row by the task.
    version_updates: dict[str, Any] = field(default_factory=dict)

    def artifact_key(self, name: str) -> str:
        """Storage key for a derived file stored next to the original PDF,
        e.g. tenants/<t>/documents/<d>/<v>/parsed.json. Same tenant prefix,
        so deleting a document's folder removes its derived files too."""
        return build_object_key(self.tenant_id, self.document_id, self.version_id, name)


@dataclass(frozen=True)
class Stage:
    name: str
    status: DocumentStatus
    handler: StageHandler
    progress: int  # % complete once this stage finishes


async def _parse(ctx: StageContext) -> None:
    """Read the PDF's text layer, tables and images; save the images.

    Raises EncryptedPdfError/CorruptPdfError/TooManyPagesError for files
    that cannot be processed (handled as permanent failures by the task).
    """
    storage = ctx.resources.storage
    options = PdfOptions.from_settings(ctx.resources.settings)
    data: bytes = await storage.get(ctx.storage_key)

    # CPU-bound: run in a thread so the worker's event loop stays responsive.
    result: ParseResult = await asyncio.to_thread(parse_pdf, data, options)

    for extracted in result.images:
        key = ctx.artifact_key(f"images/page-{extracted.page_number}-{extracted.index + 1}.png")
        await storage.put(key, extracted.png, "image/png")
        page = result.document.pages[extracted.page_number - 1]
        page.images.append(to_page_image(extracted.image, key))
    # Drop the pixel data now that it is saved; only metadata travels on.
    image_count = len(result.images)
    result.images.clear()

    ctx.artifacts.update(pdf_bytes=data, parse=result, image_count=image_count)
    ctx.version_updates["page_count"] = result.document.page_count


async def _ocr(ctx: StageContext) -> None:
    """OCR scanned pages, classify the layout, and save parsed.json.

    parsed.json is the durable output of Phase 4: Phase 5 (chunking) reads it,
    and it lets documents be re-chunked later without re-running OCR.
    """
    result: ParseResult = ctx.artifacts["parse"]
    options = PdfOptions.from_settings(ctx.resources.settings)
    data: bytes = ctx.artifacts.pop("pdf_bytes")  # last stage that needs the raw PDF

    ocr_warnings = await asyncio.to_thread(ocr_scanned_pages, data, result.document, options)
    finalize_layout(result.document)

    parsed_key = ctx.artifact_key("parsed.json")
    payload = json.dumps(result.document.to_dict(), ensure_ascii=False).encode()
    await ctx.resources.storage.put(parsed_key, payload, "application/json")

    ctx.artifacts["parsed"] = result.document
    summary = extraction_summary(
        result.document,
        image_count=ctx.artifacts.get("image_count", 0),
        warnings=result.warnings + ocr_warnings,
    )
    ctx.version_updates.update(
        page_count=result.document.page_count,
        is_scanned=bool(result.document.scanned_page_numbers),
        extraction_metadata={**summary, "parsed_key": parsed_key},
    )


async def _chunk(ctx: StageContext) -> None:
    """Split the parsed document into parent (section) and child (clause)
    chunks and save them as chunks.json — the input for embeddings (Phase 6).

    Normally the parsed document is handed over in memory by the ocr stage.
    If this stage runs on its own (e.g. re-chunking after the chunking rules
    change), it loads parsed.json instead, so OCR never has to be repeated.
    """
    parsed: ParsedDocument | None = ctx.artifacts.get("parsed")
    if parsed is None:
        raw = await ctx.resources.storage.get(ctx.artifact_key("parsed.json"))
        parsed = ParsedDocument.from_dict(json.loads(raw))

    options = ChunkingOptions.from_settings(ctx.resources.settings)
    result: ChunkingResult = await asyncio.to_thread(
        chunk_document,
        parsed,
        version_id=ctx.version_id,
        document_title=ctx.document_title,
        options=options,
    )

    chunks_key = ctx.artifact_key("chunks.json")
    payload = json.dumps(result.to_dict(options), ensure_ascii=False).encode()
    await ctx.resources.storage.put(chunks_key, payload, "application/json")

    ctx.artifacts["chunks"] = result
    # chunk_count = searchable (child) chunks, the number users care about.
    ctx.version_updates["chunk_count"] = len(result.children)
    metadata = ctx.version_updates.get("extraction_metadata")
    if metadata is not None:
        metadata.update(
            chunks_key=chunks_key,
            chunker_version=CHUNKER_VERSION,
            parent_chunks=len(result.parents),
        )


async def _load_chunks(ctx: StageContext) -> ChunkingResult:
    """Chunks from the previous stage, or from chunks.json when this stage
    runs on its own (e.g. re-embedding after an embedding-model change)."""
    chunks: ChunkingResult | None = ctx.artifacts.get("chunks")
    if chunks is None:
        raw = json.loads(await ctx.resources.storage.get(ctx.artifact_key("chunks.json")))
        chunks = ChunkingResult(chunks=[Chunk.from_dict(c) for c in raw["chunks"]])
        ctx.artifacts["chunks"] = chunks
    return chunks


async def _embed(ctx: StageContext) -> None:
    """Embed every child chunk (Gemini by default) via EmbeddingService,
    which batches, retries and caches. Parents are not embedded — they are
    never searched, only read."""
    chunks = await _load_chunks(ctx)
    provider = ctx.resources.embeddings()
    service = EmbeddingService(provider, ctx.resources.settings, ctx.resources.redis)
    vectors, stats = await service.embed_documents(
        [c.embedding_text for c in chunks.children], tenant_id=ctx.tenant_id
    )
    ctx.artifacts.update(vectors=vectors, embedding_model=embedding_model_label(provider))
    metadata = ctx.version_updates.get("extraction_metadata")
    if metadata is not None:
        metadata.update(embedding_model=embedding_model_label(provider), embedding=asdict(stats))


async def _index(ctx: StageContext) -> None:
    """Write this version's points to Qdrant and, if it is the newest version,
    make it the document's current (searched-by-default) version.

    Upsert-then-prune by deterministic chunk id makes re-processing
    idempotent and gap-free: a retried job can never leave duplicate chunks,
    and the version never disappears from search while being re-indexed.
    """
    settings = ctx.resources.settings
    client, collection = ctx.resources.qdrant, settings.qdrant_collection
    # Clear error if EMBEDDING_DIMENSION no longer matches the collection.
    await check_dimension(client, collection, settings.embedding_dimension)

    chunks = await _load_chunks(ctx)
    target = IndexTarget(
        tenant_id=ctx.tenant_id,
        document_id=ctx.document_id,
        version_id=ctx.version_id,
        version_label=ctx.version_label,
        document_title=ctx.document_title,
        contract_type=ctx.contract_type,
        is_current=ctx.is_latest_version,
        embedding_model=ctx.artifacts["embedding_model"],
        chunker_version=CHUNKER_VERSION,
    )
    points = build_points(chunks.children, ctx.artifacts["vectors"], chunks.parents, target)
    written = await upsert_version(client, collection, target, points)
    if ctx.is_latest_version:
        await mark_current_version(
            client,
            collection,
            tenant_id=ctx.tenant_id,
            document_id=ctx.document_id,
            version_id=ctx.version_id,
        )
    metadata = ctx.version_updates.get("extraction_metadata")
    if metadata is not None:
        metadata["indexed_points"] = written


PIPELINE: tuple[Stage, ...] = (
    Stage("parse", DocumentStatus.PROCESSING, _parse, 25),
    Stage("ocr", DocumentStatus.OCR_PROCESSING, _ocr, 45),
    Stage("chunk", DocumentStatus.CHUNKING, _chunk, 65),
    Stage("embed", DocumentStatus.EMBEDDING, _embed, 85),
    Stage("index", DocumentStatus.INDEXING, _index, 100),
)


async def embed_and_index(ctx: StageContext) -> None:
    """Run only the embed + index stages from the saved chunks.json.

    Used to re-embed documents after the embedding model changes, without
    repeating parsing, OCR or chunking.
    """
    await _embed(ctx)
    await _index(ctx)
