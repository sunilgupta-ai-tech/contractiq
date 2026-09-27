"""
Document ingestion pipeline definition.

The pipeline is an ordered list of stages. Each stage maps to a
`DocumentStatus`, so the status the user sees in the UI is exactly the
stage the worker is executing. Stage handlers are filled in phase by phase:

    parse  (Phase 4)  PDF text layer, tables, images      -> artifacts["parse"]
                      (Phase 16) .docx / .xlsx read as structure; JPG/PNG
                      wrapped in a one-page PDF and handled as a scan
    ocr    (Phase 4)  OCR scanned pages, layout, save JSON -> artifacts["parsed"]
                      (Phase 16) render weak-OCR pages for transcription
    describe (Phase 9) caption images, summarise tables, re-save parsed.json
                      (Phase 16) transcribe handwriting / registers first
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
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import asdict, dataclass, field
from typing import Any

from app.chunking.models import Chunk
from app.db.models import DocumentStatus, FileType
from app.document_processing.docx_parser import parse_docx
from app.document_processing.formats import format_for_storage_key
from app.document_processing.image_input import image_to_pdf, image_to_png
from app.document_processing.parser import (
    PageImage,
    ParsedDocument,
    ParsedPage,
    UnreadableFileError,
)
from app.document_processing.pymupdf_parser import open_pdf, to_page_image
from app.document_processing.xlsx_parser import parse_xlsx
from app.guardrails.prompt_injection import scan_for_injection
from app.security.pii import pii_report
from app.llm.base import embedding_model_label
from app.multimodal.transcriber import PageToTranscribe, is_weak_ocr
from app.services.chunking_service import (
    CHUNKER_VERSION,
    ChunkingOptions,
    ChunkingResult,
    chunk_document,
)
from app.services.embedding_service import EmbeddingService
from app.services.multimodal_service import enrich_document, transcribe_pages
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
    storage_key: str  # where the original file is stored (original.<ext>)
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
    """Read the file's text, tables and images; save the images.

    PDFs (and images, as one-page PDFs) go through PyMuPDF; Word and Excel
    files are read as structure (Phase 16). Raises EncryptedPdfError /
    CorruptPdfError / TooManyPagesError / UnreadableFileError for files that
    cannot be processed (handled as permanent failures by the task).
    """
    storage = ctx.resources.storage
    settings = ctx.resources.settings
    options = PdfOptions.from_settings(settings)
    data: bytes = await storage.get(ctx.storage_key)
    file_type = format_for_storage_key(ctx.storage_key).file_type
    if file_type is FileType.WORD:
        return await _parse_docx(ctx, data, options)
    if file_type is FileType.EXCEL:
        return await _parse_xlsx(ctx, data)
    photo: tuple[bytes, int, int] | None = None
    if file_type is FileType.IMAGE:
        try:
            photo = await asyncio.to_thread(
                image_to_png, data, max_side_px=settings.max_image_side_px
            )
        except Exception as exc:  # decoding errors vary by image library
            raise UnreadableFileError("The image is damaged or could not be read.") from exc
        data = await asyncio.to_thread(image_to_pdf, *photo, dpi=options.ocr_dpi)

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

    if photo is not None:
        # The photo itself is captioned (what it shows: a receipt, a stamp,
        # a whiteboard), in addition to the OCR of its text.
        png, width, height = photo
        key = ctx.artifact_key("images/page-1-1.png")
        await storage.put(key, png, "image/png")
        page = result.document.pages[0]
        page.images.append(
            PageImage(
                bbox=(0.0, 0.0, page.width, page.height),
                width_px=width,
                height_px=height,
                storage_key=key,
            )
        )
        image_count += 1
        result.document.metadata["format"] = "image"

    ctx.artifacts.update(pdf_bytes=data, parse=result, image_count=image_count)
    ctx.version_updates["page_count"] = result.document.page_count


async def _parse_docx(ctx: StageContext, data: bytes, options: PdfOptions) -> None:
    try:
        parsed = await asyncio.to_thread(
            parse_docx,
            data,
            max_pages=options.max_pages,
            max_images=options.max_images,
            min_image_dimension_px=options.min_image_dimension_px,
        )
    except Exception as exc:  # python-docx/lxml raise many types for broken files
        raise UnreadableFileError("The Word file is damaged or could not be read.") from exc
    for index, image in enumerate(parsed.images):
        key = ctx.artifact_key(f"images/page-{image.page_number}-{index + 1}.png")
        await ctx.resources.storage.put(key, image.png, "image/png")
        page = parsed.document.pages[image.page_number - 1]
        page.images.append(
            PageImage(
                bbox=(0.0, image.y, page.width, image.y + 1.0),
                width_px=image.width_px,
                height_px=image.height_px,
                storage_key=key,
            )
        )
    result = ParseResult(parsed.document, warnings=parsed.warnings)
    ctx.artifacts.update(pdf_bytes=None, parse=result, image_count=len(parsed.images))
    ctx.version_updates["page_count"] = parsed.document.page_count


async def _parse_xlsx(ctx: StageContext, data: bytes) -> None:
    try:
        parsed = await asyncio.to_thread(
            parse_xlsx, data, max_cells=ctx.resources.settings.max_spreadsheet_cells
        )
    except Exception as exc:  # openpyxl raises many types for broken files
        raise UnreadableFileError("The Excel file is damaged or could not be read.") from exc
    result = ParseResult(parsed.document, warnings=parsed.warnings)
    ctx.artifacts.update(pdf_bytes=None, parse=result, image_count=0)
    ctx.version_updates["page_count"] = parsed.document.page_count


# Rendering resolution for pages sent to the vision model: legible
# handwriting, at a fraction of the pixels of the 300-DPI OCR render.
_TRANSCRIBE_DPI = 200


def _render_pages(data: bytes, numbers: list[int]) -> list[tuple[int, bytes]]:
    with open_pdf(data) as doc:
        return [
            (n, bytes(doc[n - 1].get_pixmap(dpi=_TRANSCRIBE_DPI).tobytes("png"))) for n in numbers
        ]


async def _weak_pages(
    ctx: StageContext, data: bytes, pages: list[ParsedPage]
) -> list[PageToTranscribe]:
    """Scanned pages (and photos) whose OCR is weak, rendered and saved for
    the describe stage to transcribe (Phase 16)."""
    settings = ctx.resources.settings
    if not (settings.multimodal_enabled and settings.handwriting_transcription_enabled):
        return []
    weak = [
        p.number
        for p in pages
        if is_weak_ocr(p, min_confidence=settings.transcribe_below_ocr_confidence)
    ][: settings.max_transcribed_pages_per_document]
    if not weak:
        return []
    targets = []
    for number, png in await asyncio.to_thread(_render_pages, data, weak):
        key = ctx.artifact_key(f"pages/page-{number}.png")
        await ctx.resources.storage.put(key, png, "image/png")
        targets.append(PageToTranscribe(number, key))
    return targets


async def _ocr(ctx: StageContext) -> None:
    """OCR scanned pages, classify the layout, and save parsed.json.

    parsed.json is the durable output of Phase 4: Phase 5 (chunking) reads it,
    and it lets documents be re-chunked later without re-running OCR.
    """
    result: ParseResult = ctx.artifacts["parse"]
    options = PdfOptions.from_settings(ctx.resources.settings)
    data: bytes | None = ctx.artifacts.pop("pdf_bytes")  # last stage that needs the raw PDF

    ocr_warnings: list[str] = []
    if data is not None:
        ocr_warnings = await asyncio.to_thread(ocr_scanned_pages, data, result.document, options)
        finalize_layout(result.document)
        ctx.artifacts["transcribe"] = await _weak_pages(ctx, data, result.document.pages)
    # Word and Excel (data is None) have no scans, and their block kinds come
    # from the file's own structure, so OCR and layout labelling are skipped.

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
        extraction_metadata={
            **summary,
            "format": result.document.metadata.get("format", "pdf"),
            "parsed_key": parsed_key,
        },
    )


async def _describe(ctx: StageContext) -> None:
    """Caption images and summarise tables (Phase 9), then re-save
    parsed.json with them, so re-chunking never repeats the model calls.

    Never fails the document: see app/services/multimodal_service.py.
    """
    parsed: ParsedDocument | None = ctx.artifacts.get("parsed")
    if parsed is None:
        raw = await ctx.resources.storage.get(ctx.artifact_key("parsed.json"))
        parsed = ParsedDocument.from_dict(json.loads(raw))
        ctx.artifacts["parsed"] = parsed

    # Handwriting and registers first, so captions and table summaries see
    # the transcribed text and tables.
    transcription = await transcribe_pages(
        parsed,
        ctx.artifacts.get("transcribe", []),
        tenant_id=ctx.tenant_id,
        settings=ctx.resources.settings,
        provider_factory=ctx.resources.vision,
        storage=ctx.resources.storage,
        redis=ctx.resources.redis,
    )
    result = await enrich_document(
        parsed,
        tenant_id=ctx.tenant_id,
        settings=ctx.resources.settings,
        provider_factory=ctx.resources.vision,
        storage=ctx.resources.storage,
        redis=ctx.resources.redis,
    )
    changed = result.stats.api_calls or result.stats.cache_hits
    if changed or transcription.transcribed_pages:
        parsed_key = ctx.artifact_key("parsed.json")
        payload = json.dumps(parsed.to_dict(), ensure_ascii=False).encode()
        await ctx.resources.storage.put(parsed_key, payload, "application/json")
    metadata = ctx.version_updates.get("extraction_metadata")
    if metadata is not None:
        metadata["multimodal"] = asdict(result.stats)
        metadata["review"] = review_needed(
            parsed,
            transcribed=set(transcription.transcribed_pages),
            min_confidence=ctx.resources.settings.transcribe_below_ocr_confidence,
        )
        metadata["transcribed_pages"] = transcription.transcribed_pages
        metadata["transcription"] = asdict(transcription.stats)
        metadata["warnings"] = (
            metadata.get("warnings", []) + transcription.warnings + result.warnings
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
            injection=injection_report(c.text for c in result.children),
        )
        if ctx.resources.settings.pii_detection_enabled:
            # Phase 24: counts of personal data per kind (never the values).
            metadata["pii"] = pii_report(c.text for c in result.children)


def review_needed(
    parsed: ParsedDocument, *, transcribed: set[int], min_confidence: float
) -> dict[str, Any]:
    """Phase 21: should a person check this document's text?

    Yes when the recovered text may be wrong or missing: scanned pages whose
    OCR stayed weak (not transcribed by the vision model — disabled, over the
    per-document cap, or failed), scanned pages with no text at all, or a
    PDF only the fallback reader could open. The document is still indexed;
    the flag only tells people to double-check answers from it.
    """
    weak, empty = [], []
    for page in parsed.pages:
        if not page.is_scanned or page.number in transcribed:
            continue
        if not any(b.text.strip() for b in page.blocks):
            empty.append(page.number)
        elif is_weak_ocr(page, min_confidence=min_confidence):
            weak.append(page.number)
    reasons = []
    if weak:
        reasons.append("low_ocr_confidence")
    if empty:
        reasons.append("no_text_found")
    if parsed.metadata.get("parser") == "pdfplumber-fallback":
        reasons.append("damaged_pdf_recovered")
    return {"required": bool(reasons), "reasons": reasons, "pages": sorted(weak + empty)}


def injection_report(texts: Iterable[str]) -> dict[str, Any]:
    """Phase 20: passages that read like instructions to an AI ("ignore
    previous instructions", forged delimiters...). Nothing is removed — the
    text is still the document's and is always sent to the model as data —
    but the count is recorded and shown, so a planted document is visible."""
    flagged, rules = 0, set()
    for text in texts:
        matched = scan_for_injection(text).matched_rules
        if matched:
            flagged += 1
            rules.update(matched)
    return {"chunks": flagged, "rules": sorted(rules)}


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
    # Shown to users as part of content extraction: no new status, so no
    # database enum migration and no change to the UI's stepper.
    Stage("describe", DocumentStatus.OCR_PROCESSING, _describe, 55),
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
