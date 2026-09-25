"""
Document ingestion pipeline definition.

The pipeline is an ordered list of stages. Each stage maps to a
`DocumentStatus`, so the status the user sees in the UI is exactly the
stage the worker is executing. Stage handlers are filled in phase by phase:

    parse  (Phase 4)  PDF text layer, tables, images      -> artifacts["parse"]
    ocr    (Phase 4)  OCR scanned pages, layout, save JSON -> artifacts["parsed"]
    chunk  (Phase 5)  section/clause-aware chunks
    embed  (Phase 6)  embeddings
    index  (Phase 6)  Qdrant upsert

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
from dataclasses import dataclass, field
from typing import Any

from app.db.models import DocumentStatus
from app.document_processing.pymupdf_parser import to_page_image
from app.services.ocr_service import ocr_scanned_pages
from app.services.pdf_service import (
    ParseResult,
    PdfOptions,
    extraction_summary,
    finalize_layout,
    parse_pdf,
)
from app.storage import build_object_key

StageHandler = Callable[["StageContext"], Awaitable[None]]


@dataclass
class StageContext:
    """Mutable state handed from stage to stage for one document version."""

    tenant_id: str
    document_id: str
    version_id: str
    storage_key: str  # where the original PDF is stored
    resources: Any
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
    """Phase 5: section/clause-aware chunking of artifacts["parsed"]."""


async def _embed(ctx: StageContext) -> None:
    """Phase 6: batch embeddings via EmbeddingProvider."""


async def _index(ctx: StageContext) -> None:
    """Phase 6: delete this version's old points, then upsert new ones.

    Delete-then-upsert keyed by version_id makes re-processing idempotent:
    a retried job can never leave duplicate chunks in Qdrant.
    """


PIPELINE: tuple[Stage, ...] = (
    Stage("parse", DocumentStatus.PROCESSING, _parse, 25),
    Stage("ocr", DocumentStatus.OCR_PROCESSING, _ocr, 45),
    Stage("chunk", DocumentStatus.CHUNKING, _chunk, 65),
    Stage("embed", DocumentStatus.EMBEDDING, _embed, 85),
    Stage("index", DocumentStatus.INDEXING, _index, 100),
)
