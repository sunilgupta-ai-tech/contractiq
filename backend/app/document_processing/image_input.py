"""
JPG / PNG uploads -> a one-page PDF (Phase 16).

An uploaded photo or scan is wrapped in a single-page PDF with no text
layer, so it goes through exactly the path of a scanned PDF page: OCR,
layout, weak-OCR transcription by the vision model, chunking and citations
("p. 1"). No second pipeline to maintain.

Before wrapping:
  * EXIF orientation is applied — phone photos are often stored sideways
    with a "rotate me" flag that OCR would otherwise ignore;
  * the image is scaled down to `max_side_px` on its long side, bounding
    OCR time for 50-megapixel photos without hurting legibility;
  * the page is sized so that rendering at the OCR DPI gives back the
    image's own pixels (no blurry upscaling, no wasted downscaling).
"""

from __future__ import annotations

import io

import pymupdf
from PIL import Image, ImageOps


def image_to_png(data: bytes, *, max_side_px: int) -> tuple[bytes, int, int]:
    """Upright, size-bounded RGB PNG of the upload, with its size in pixels."""
    with Image.open(io.BytesIO(data)) as source:
        image = ImageOps.exif_transpose(source) or source
        image = image.convert("RGB")
        if max(image.size) > max_side_px:
            image.thumbnail((max_side_px, max_side_px), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        image.save(out, "PNG", optimize=True)
        return out.getvalue(), image.width, image.height


def image_to_pdf(png: bytes, width_px: int, height_px: int, *, dpi: int) -> bytes:
    """A one-page PDF showing `png` edge to edge, sized for `dpi`."""
    points_per_px = 72.0 / dpi
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=width_px * points_per_px, height=height_px * points_per_px)
        page.insert_image(page.rect, stream=png)
        return bytes(pdf.tobytes(deflate=True))
