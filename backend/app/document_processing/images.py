"""
Export of meaningful embedded images (charts, diagrams, signatures, stamps).

Phase 9 (multimodal RAG) will caption these images so questions like "what
does the escalation diagram show?" can be answered. Phase 4 only saves them.

What is skipped, and why
------------------------
* Small images (logos, icons, decorative rules): below `min_dimension_px` on
  either side they carry no contract meaning and would flood storage.
* The full-page image of a scanned page: its content is captured by OCR,
  and storing it would duplicate the original PDF page by page.
* The same image object repeated on many pages (a letterhead logo): exported
  once, the first time it appears.
"""

from __future__ import annotations

import pymupdf

from app.document_processing.pymupdf_parser import ImageOnPage


def select_images(
    images: list[ImageOnPage],
    *,
    page_is_scanned: bool,
    min_dimension_px: int,
    seen_xrefs: set[int],
) -> list[ImageOnPage]:
    """Pick the images on one page worth exporting.

    `seen_xrefs` is shared across the whole document and updated in place,
    which is how repeated images are exported only once.
    """
    if page_is_scanned:
        return []
    chosen = []
    for image in images:
        if image.xref == 0 or image.xref in seen_xrefs:
            continue
        if min(image.width_px, image.height_px) < min_dimension_px:
            continue
        seen_xrefs.add(image.xref)
        chosen.append(image)
    return chosen


def image_png_bytes(doc: pymupdf.Document, xref: int) -> bytes | None:
    """Render an embedded image object as PNG bytes.

    PNG is lossless and universally readable by vision models. CMYK images
    (common in print-produced PDFs) are converted to RGB first, because PNG
    cannot store CMYK.
    Returns None if the image object cannot be decoded (rare, broken PDFs);
    a single bad image must not fail the whole document.
    """
    try:
        pix = pymupdf.Pixmap(doc, xref)
        if pix.colorspace and pix.colorspace.n > 3:  # CMYK -> RGB
            pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
        return bytes(pix.tobytes("png"))
    except Exception:  # noqa: BLE001 — see docstring
        return None
