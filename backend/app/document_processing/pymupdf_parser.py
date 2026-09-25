"""
Text-layer extraction with PyMuPDF.

Why PyMuPDF
-----------
It is the fastest mature PDF library for Python (a C core, MuPDF), and it
reports what later stages need: every text block with its position, font
size and weight (used to detect headings), plus embedded images with their
on-page position. It also renders pages to images for OCR.

Licence note: PyMuPDF is AGPL-3.0. Using it in a closed-source commercial
product requires a commercial licence from Artifex — confirm before shipping.

What this module decides
------------------------
* Can the file be opened at all? (encrypted/corrupt -> permanent errors)
* For each page: its text blocks, its embedded images, and whether the page
  is "scanned" (no usable text layer, so it must go to OCR).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

import pymupdf

from app.document_processing.parser import (
    BBox,
    CorruptPdfError,
    EncryptedPdfError,
    PageImage,
    ParsedPage,
    TextBlock,
)

# A page with fewer non-whitespace characters than this has no meaningful
# text layer. (Scans often carry a stray page number or scanner stamp as text.)
MIN_TEXT_CHARS = 25
# ...and if images cover at least this share of it, it is a scanned page.
SCANNED_IMAGE_COVERAGE = 0.5

# PyMuPDF span flag bit for bold text.
_BOLD_FLAG = 1 << 4
# Text-extraction flags: keep whitespace and ligatures as-is, but do not embed
# image bytes in the output (we read images separately and only when needed).
_TEXT_FLAGS = pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES
_SPACES = re.compile(r"[ \t ]+")


def open_pdf(data: bytes) -> pymupdf.Document:
    """Open a PDF from bytes, turning library errors into user-facing ones.

    Encryption: a PDF can have an *owner* password (restricts printing or
    copying) and/or a *user* password (required to open it). Owner-only PDFs
    open normally and are processed; only a user password blocks us.
    """
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:  # PyMuPDF raises several types for unreadable files
        raise CorruptPdfError() from exc
    if doc.needs_pass and not doc.authenticate(""):
        doc.close()
        raise EncryptedPdfError()
    if doc.page_count == 0:
        doc.close()
        raise CorruptPdfError("The PDF has no pages.")
    return doc


def document_metadata(doc: pymupdf.Document) -> dict[str, str]:
    """The PDF's info dictionary (title, author, creation date, ...), empty values dropped."""
    return {k: v for k, v in (doc.metadata or {}).items() if v}


@dataclass(frozen=True)
class ImageOnPage:
    """An embedded image found on a page, before it is saved to storage."""

    xref: int  # PyMuPDF's handle for the image object inside the PDF
    bbox: BBox
    width_px: int
    height_px: int


def extract_page(page: pymupdf.Page, number: int) -> tuple[ParsedPage, list[ImageOnPage]]:
    """Read one page's text blocks and images and decide if it is scanned.

    Returns the ParsedPage (text blocks not yet classified — see layout.py)
    and the images found on it (saved later, if large enough to matter).
    """
    rect = page.rect
    blocks = _text_blocks(page)
    images = _images(page)

    text_chars = sum(len("".join(b.text.split())) for b in blocks)
    coverage = _image_coverage(images, rect.width * rect.height)
    is_scanned = is_scanned_page(text_chars, coverage)

    parsed = ParsedPage(
        number=number,
        width=round(rect.width, 2),
        height=round(rect.height, 2),
        # A scan's few stray characters (e.g. a stamped page number) are noise;
        # OCR will produce the page's real text instead.
        blocks=[] if is_scanned else blocks,
        is_scanned=is_scanned,
    )
    return parsed, images


def is_scanned_page(text_chars: int, image_coverage: float) -> bool:
    """Scanned = (almost) no text layer AND mostly covered by images.

    Both conditions matter: a blank page has no text but no image either
    (nothing to OCR), and a "searchable" scan already has an invisible OCR
    text layer, so it has plenty of text and is treated as a normal page.
    """
    return text_chars < MIN_TEXT_CHARS and image_coverage >= SCANNED_IMAGE_COVERAGE


def _text_blocks(page: pymupdf.Page) -> list[TextBlock]:
    """Convert PyMuPDF's block -> line -> span tree into TextBlocks.

    `sort=True` asks PyMuPDF for top-to-bottom, left-to-right reading order,
    which is correct for single-column contracts (the common case).
    """
    blocks: list[TextBlock] = []
    for block in page.get_text("dict", flags=_TEXT_FLAGS, sort=True)["blocks"]:
        if block.get("type") != 0:  # 0 = text; 1 = image
            continue
        lines: list[str] = []
        size_weight: Counter[float] = Counter()  # font size -> number of characters
        bold_chars = total_chars = 0
        for line in block["lines"]:
            spans = line["spans"]
            lines.append("".join(s["text"] for s in spans))
            for span in spans:
                n = len(span["text"].strip())
                total_chars += n
                size_weight[round(span["size"], 1)] += n
                if span["flags"] & _BOLD_FLAG or "bold" in span["font"].lower():
                    bold_chars += n
        text = _join_lines(lines)
        if not text:
            continue
        blocks.append(
            TextBlock(
                text=text,
                bbox=_round_bbox(block["bbox"]),
                # The size most characters use, so one large drop-cap or a
                # small footnote marker doesn't misrepresent the block.
                font_size=size_weight.most_common(1)[0][0] if size_weight else None,
                is_bold=total_chars > 0 and bold_chars / total_chars >= 0.6,
            )
        )
    return blocks


def _join_lines(lines: list[str]) -> str:
    """Join visual lines into one paragraph string.

    PDF text is stored line by line exactly as laid out, so a sentence that
    wraps becomes two lines. Lines are joined with a space, except that a
    word hyphenated across the line break ("termi-" + "nation") is re-joined.
    """
    out = ""
    for raw in lines:
        line = _SPACES.sub(" ", raw).strip()
        if not line:
            continue
        if out.endswith("-") and line[:1].islower():
            out = out[:-1] + line
        else:
            out = f"{out} {line}" if out else line
    return out


def _images(page: pymupdf.Page) -> list[ImageOnPage]:
    images = []
    for info in page.get_image_info(xrefs=True):
        # xref 0 means an inline image with no reusable object; we can still
        # measure it for scan detection, but cannot export it later.
        images.append(
            ImageOnPage(
                xref=info.get("xref", 0),
                bbox=_round_bbox(info["bbox"]),
                width_px=int(info.get("width", 0)),
                height_px=int(info.get("height", 0)),
            )
        )
    return images


def _image_coverage(images: list[ImageOnPage], page_area: float) -> float:
    """Share of the page covered by images (capped at 1.0).

    Overlapping images are simply summed — an overestimate that only matters
    for pages that are already mostly image, which is exactly what we're testing.
    """
    if page_area <= 0:
        return 0.0
    area = sum(max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1]) for b in (i.bbox for i in images))
    return min(area / page_area, 1.0)


def _round_bbox(bbox: Sequence[float]) -> BBox:
    """PyMuPDF gives boxes as tuples or Rect objects; normalise to a rounded tuple."""
    x0, y0, x1, y1 = (float(v) for v in bbox)
    return (round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2))


def to_page_image(image: ImageOnPage, storage_key: str) -> PageImage:
    return PageImage(
        bbox=image.bbox,
        width_px=image.width_px,
        height_px=image.height_px,
        storage_key=storage_key,
    )
