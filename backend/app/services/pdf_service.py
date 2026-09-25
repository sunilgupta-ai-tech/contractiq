"""
PDF extraction: turns an uploaded PDF's bytes into a ParsedDocument.

Which tool does what
--------------------
    PyMuPDF     text blocks (+ fonts, positions), images, scanned-page detection
    pdfplumber  tables, on pages that have a real text layer
    Tesseract   text for scanned pages          -> see ocr_service.py
    layout.py   headings / lists / headers / footers / table text

Called by the worker in two steps, matching the statuses users see:
    "parse" stage  (PROCESSING)      -> parse_pdf()
    "ocr" stage    (OCR_PROCESSING)  -> ocr_service.ocr_scanned_pages(), then finalize_layout()

All functions here are synchronous and CPU-bound. The worker calls them via
`asyncio.to_thread` so one large PDF doesn't block its event loop (which is
also serving other jobs and the queue heartbeat).

Failure policy
--------------
* The file itself is unusable (encrypted, corrupt, too many pages): raise a
  PdfProcessingError — permanent, shown to the user, not retried.
* One part of the file misbehaves (a broken image, a table pdfplumber
  cannot read): record a warning and continue. A contract with one odd table
  is still worth indexing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pdfplumber
import pymupdf

from app.core.config import Settings
from app.core.logging import get_logger
from app.document_processing.images import image_png_bytes, select_images
from app.document_processing.layout import classify_blocks
from app.document_processing.ocr import tesseract_version
from app.document_processing.parser import ParsedDocument, TooManyPagesError
from app.document_processing.pdfplumber_parser import extract_tables
from app.document_processing.pymupdf_parser import (
    ImageOnPage,
    document_metadata,
    extract_page,
    open_pdf,
)

logger = get_logger(__name__)


@dataclass(frozen=True)
class PdfOptions:
    """Processing limits and OCR settings (from environment via Settings)."""

    max_pages: int = 2000
    min_image_dimension_px: int = 150
    max_images: int = 200
    ocr_enabled: bool = True
    ocr_dpi: int = 300
    ocr_languages: str = "eng"
    ocr_timeout_s: int = 120

    @classmethod
    def from_settings(cls, settings: Settings) -> PdfOptions:
        return cls(
            max_pages=settings.max_pdf_pages,
            min_image_dimension_px=settings.min_image_dimension_px,
            max_images=settings.max_images_per_document,
            ocr_enabled=settings.ocr_enabled,
            ocr_dpi=settings.ocr_dpi,
            ocr_languages=settings.ocr_languages,
            ocr_timeout_s=settings.ocr_page_timeout_s,
        )


@dataclass
class ExtractedImage:
    """An image to save to storage; `index` numbers images within their page."""

    page_number: int
    index: int
    image: ImageOnPage
    png: bytes


@dataclass
class ParseResult:
    document: ParsedDocument
    images: list[ExtractedImage] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def parse_pdf(data: bytes, options: PdfOptions) -> ParseResult:
    """Step 1: read text layer, images and tables. No OCR yet.

    Raises EncryptedPdfError / CorruptPdfError / TooManyPagesError for files
    that cannot be processed at all.
    """
    warnings: list[str] = []
    pages = []
    images: list[ExtractedImage] = []
    seen_xrefs: set[int] = set()

    with open_pdf(data) as doc:
        # Checked before reading any page, so a 50,000-page file fails in
        # milliseconds instead of occupying a worker for an hour.
        if doc.page_count > options.max_pages:
            raise TooManyPagesError(
                f"The PDF has {doc.page_count} pages; the limit is {options.max_pages}."
            )
        for index, page in enumerate(doc):
            parsed, found = extract_page(page, index + 1)
            pages.append(parsed)
            selected = select_images(
                found,
                page_is_scanned=parsed.is_scanned,
                min_dimension_px=options.min_image_dimension_px,
                seen_xrefs=seen_xrefs,
            )
            for image_index, image in enumerate(selected):
                if len(images) >= options.max_images:
                    if not any("image limit" in w for w in warnings):
                        warnings.append(
                            f"Only the first {options.max_images} images were saved "
                            "(image limit reached)."
                        )
                    break
                png = image_png_bytes(doc, image.xref)
                if png is None:
                    warnings.append(f"An image on page {parsed.number} could not be decoded.")
                    continue
                images.append(ExtractedImage(parsed.number, image_index, image, png))
        metadata = document_metadata(doc)

    # Tables only exist as vector lines on text-layer pages.
    digital_pages = [p.number for p in pages if not p.is_scanned and p.blocks]
    try:
        for number, tables in extract_tables(data, digital_pages).items():
            pages[number - 1].tables = tables
    except Exception as exc:  # noqa: BLE001 — see "Failure policy" above
        logger.warning("table_extraction_failed", extra={"error": repr(exc)})
        warnings.append("Tables could not be extracted; table text is kept as plain text.")

    return ParseResult(ParsedDocument(pages=pages, metadata=metadata), images, warnings)


def finalize_layout(document: ParsedDocument) -> None:
    """Step 3 (after OCR): label every block. Runs last because header/footer
    detection compares all pages, including the ones OCR just filled in."""
    classify_blocks(document.pages)


def extraction_summary(
    document: ParsedDocument, *, image_count: int, warnings: list[str]
) -> dict[str, Any]:
    """Compact facts about the extraction, stored on the DocumentVersion row
    (`extraction_metadata`) for the UI, support and debugging.

    Engine versions are recorded because re-processing the same PDF after a
    library upgrade can change its text; this makes such changes traceable.
    """
    confidences = [p.ocr_confidence for p in document.pages if p.ocr_confidence is not None]
    return {
        "pages": document.page_count,
        "scanned_pages": document.scanned_page_numbers,
        "tables": sum(len(p.tables) for p in document.pages),
        "images": image_count,
        "ocr_mean_confidence": (
            round(sum(confidences) / len(confidences), 1) if confidences else None
        ),
        "warnings": warnings,
        "engines": {
            "pymupdf": pymupdf.__version__,
            "pdfplumber": pdfplumber.__version__,
            "tesseract": tesseract_version(),
        },
    }
