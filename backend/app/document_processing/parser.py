"""
The normalised result of PDF processing, plus the errors processing can raise.

Where this sits in the pipeline
-------------------------------
    upload -> worker "parse" stage -> worker "ocr" stage -> ParsedDocument
           -> saved as parsed.json next to the PDF -> (Phase 5) chunking

Why one shared model
--------------------
Three libraries contribute to a parsed page: PyMuPDF (text layer, fonts,
images), pdfplumber (tables) and Tesseract (OCR for scanned pages). Each
describes a page differently. Converting everything into the dataclasses
below means chunking, citations and search never need to know which
library produced a piece of text, and any one library can be replaced
without touching downstream code.

Coordinates
-----------
Every `bbox` is (x0, y0, x1, y1) in PDF points (1/72 inch) with the origin
at the page's top-left corner — the convention PyMuPDF uses. OCR results
are converted from image pixels into the same space. Keeping positions lets
a future citation highlight the exact region of the page an answer came from.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

BBox = tuple[float, float, float, float]  # (x0, y0, x1, y1) in PDF points


class BlockKind(StrEnum):
    """What a text block is, as decided by `layout.classify_blocks`."""

    HEADING = "heading"  # e.g. "8. TERMINATION" — becomes a section boundary in Phase 5
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"  # "(a) ...", "• ..."
    TABLE_TEXT = "table_text"  # text that also lives in a Table; excluded to avoid duplicates
    HEADER = "header"  # repeated at the top of pages ("ACME CONFIDENTIAL")
    FOOTER = "footer"  # repeated at the bottom ("Page 3 of 40")


# Blocks that are part of the page "furniture", not the contract's content.
# They are kept in the model (useful for debugging) but excluded from text.
NON_CONTENT_KINDS = frozenset({BlockKind.TABLE_TEXT, BlockKind.HEADER, BlockKind.FOOTER})


class TextSource(StrEnum):
    TEXT_LAYER = "text_layer"  # the PDF contained real, selectable text
    OCR = "ocr"  # text recognised from a page image by Tesseract


@dataclass
class TextBlock:
    """A run of text that belongs together (usually one paragraph)."""

    text: str
    bbox: BBox
    kind: BlockKind = BlockKind.PARAGRAPH
    # Dominant font size/weight of the block. Unknown (None/False) for OCR
    # text, so layout falls back to numbering patterns for OCR headings.
    font_size: float | None = None
    is_bold: bool = False
    source: TextSource = TextSource.TEXT_LAYER
    confidence: float | None = None  # OCR only: mean word confidence, 0-100


@dataclass
class Table:
    """A table as a grid of cleaned cell strings (first row is usually the header)."""

    bbox: BBox
    rows: list[list[str]]

    def to_markdown(self) -> str:
        """Markdown keeps the row/column structure intact when the table is
        later placed into a chunk or an LLM prompt; flattened cell text would
        lose which value belongs to which column."""
        if not self.rows:
            return ""
        width = max(len(r) for r in self.rows)
        grid = [[c.replace("|", "\\|") for c in r] + [""] * (width - len(r)) for r in self.rows]
        header, *body = grid
        lines = ["| " + " | ".join(header) + " |", "|" + " --- |" * width]
        lines += ["| " + " | ".join(row) + " |" for row in body]
        return "\n".join(lines)


@dataclass
class PageImage:
    """An embedded image worth keeping (charts, signatures, diagrams).

    Only metadata lives here; the pixels are saved to object storage and
    referenced by `storage_key`, so parsed.json stays small.
    """

    bbox: BBox
    width_px: int
    height_px: int
    storage_key: str | None = None


@dataclass
class ParsedPage:
    number: int  # 1-based, as shown to users in citations ("p. 12")
    width: float
    height: float
    blocks: list[TextBlock] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    images: list[PageImage] = field(default_factory=list)
    is_scanned: bool = False  # no usable text layer; text (if any) came from OCR
    ocr_confidence: float | None = None

    @property
    def text(self) -> str:
        """The page's readable content, without headers/footers/table duplicates."""
        return "\n\n".join(b.text for b in self.blocks if b.kind not in NON_CONTENT_KINDS)


@dataclass
class ParsedDocument:
    pages: list[ParsedPage]
    metadata: dict[str, Any] = field(default_factory=dict)  # PDF info dict: title, author, ...

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def scanned_page_numbers(self) -> list[int]:
        return [p.number for p in self.pages if p.is_scanned]

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe form for parsed.json (enums serialise as their string values)."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ParsedDocument:
        """Inverse of `to_dict`, used by Phase 5 to load parsed.json."""
        pages = [
            ParsedPage(
                number=p["number"],
                width=p["width"],
                height=p["height"],
                blocks=[
                    TextBlock(
                        **{
                            **b,
                            "bbox": tuple(b["bbox"]),
                            "kind": BlockKind(b["kind"]),
                            "source": TextSource(b["source"]),
                        }
                    )
                    for b in p["blocks"]
                ],
                tables=[Table(bbox=tuple(t["bbox"]), rows=t["rows"]) for t in p["tables"]],
                images=[PageImage(**{**i, "bbox": tuple(i["bbox"])}) for i in p["images"]],
                is_scanned=p["is_scanned"],
                ocr_confidence=p["ocr_confidence"],
            )
            for p in data["pages"]
        ]
        return cls(pages=pages, metadata=data.get("metadata", {}))


# --- Errors ------------------------------------------------------------------------


class PdfProcessingError(Exception):
    """A *permanent* problem with the file itself.

    Retrying cannot fix a password-protected or corrupt PDF, so the worker
    marks the job FAILED immediately (no arq retries) and shows
    `user_message` in the UI. Anything that is not a PdfProcessingError is
    treated as transient (e.g. storage timeout) and retried.
    """

    user_message = "The document could not be processed."

    def __init__(self, user_message: str | None = None) -> None:
        self.user_message = user_message or self.user_message
        super().__init__(self.user_message)


class EncryptedPdfError(PdfProcessingError):
    user_message = "The PDF is password-protected. Upload an unlocked copy."


class CorruptPdfError(PdfProcessingError):
    user_message = "The PDF is damaged or not a valid PDF file."


class TooManyPagesError(PdfProcessingError):
    user_message = "The PDF has too many pages to process."
