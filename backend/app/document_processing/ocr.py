"""
OCR of scanned pages with Tesseract.

How a scanned page becomes text
-------------------------------
1. PyMuPDF renders the page to a greyscale image at `dpi` (300 by default —
   Tesseract's accuracy drops noticeably below ~250 DPI on small contract print).
2. Tesseract returns every recognised word with its pixel box, its position
   in Tesseract's own block/paragraph structure, and a confidence (0-100).
3. Words are grouped back into paragraphs, and pixel boxes are converted to
   PDF points so OCR text has the same coordinates as text-layer text.

Requires the `tesseract` binary (installed in the worker image) plus a
language pack per language in `languages` ("eng", or e.g. "eng+deu").
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

import pymupdf
import pytesseract
from PIL import Image

from app.document_processing.parser import BlockKind, TextBlock, TextSource

# Tesseract "page segmentation mode" 3 = fully automatic layout analysis,
# the right default for full pages with headings and paragraphs.
_TESSERACT_CONFIG = "--psm 3"


@dataclass(frozen=True)
class OcrResult:
    blocks: list[TextBlock]
    mean_confidence: float | None  # None when no words were recognised


def ocr_page(page: pymupdf.Page, *, dpi: int, languages: str, timeout_s: int) -> OcrResult:
    """OCR one page. Raises RuntimeError if Tesseract exceeds `timeout_s`
    (pytesseract's behaviour), which the caller records as a page warning."""
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
    # pix.w/pix.h rather than pix.width/pix.height: same values, but PyMuPDF's
    # type hints mis-declare `width`/`height` as methods.
    image = Image.frombytes("L", (pix.w, pix.h), pix.samples)
    data = pytesseract.image_to_data(
        image,
        lang=languages,
        config=_TESSERACT_CONFIG,
        output_type=pytesseract.Output.DICT,
        timeout=timeout_s,
    )
    return words_to_blocks(data, scale=72.0 / dpi)


def words_to_blocks(data: dict[str, list[Any]], *, scale: float) -> OcrResult:
    """Group Tesseract's word table into paragraph TextBlocks.

    `data` is pytesseract's DICT output: parallel lists, one entry per
    detected element. `scale` converts image pixels to PDF points
    (72 points per inch / render DPI).

    Words with confidence -1 are structural rows (page/block/line markers),
    not words, and empty strings are noise; both are skipped.
    """
    paragraphs: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, word in enumerate(data["text"]):
        if word.strip() and float(data["conf"][i]) >= 0:
            paragraphs[(data["block_num"][i], data["par_num"][i])].append(i)

    blocks: list[TextBlock] = []
    all_conf: list[float] = []
    for indexes in paragraphs.values():  # dicts keep insertion (= reading) order
        confs = [float(data["conf"][i]) for i in indexes]
        all_conf += confs
        x0 = min(data["left"][i] for i in indexes)
        y0 = min(data["top"][i] for i in indexes)
        x1 = max(data["left"][i] + data["width"][i] for i in indexes)
        y1 = max(data["top"][i] + data["height"][i] for i in indexes)
        blocks.append(
            TextBlock(
                text=" ".join(data["text"][i].strip() for i in indexes),
                bbox=(
                    round(x0 * scale, 2),
                    round(y0 * scale, 2),
                    round(x1 * scale, 2),
                    round(y1 * scale, 2),
                ),
                kind=BlockKind.PARAGRAPH,
                source=TextSource.OCR,
                confidence=round(sum(confs) / len(confs), 1),
            )
        )
    mean = round(sum(all_conf) / len(all_conf), 1) if all_conf else None
    return OcrResult(blocks=blocks, mean_confidence=mean)


def tesseract_version() -> str | None:
    """Installed Tesseract version, recorded with each document's extraction
    metadata so OCR differences can be traced to an engine upgrade."""
    try:
        return str(pytesseract.get_tesseract_version())
    except pytesseract.TesseractNotFoundError:
        return None
