"""
Builds small, realistic test PDFs in memory with PyMuPDF.

Generating fixtures in code (instead of committing binary PDFs) keeps every
test's input readable and makes it obvious what each test depends on.
"""

from __future__ import annotations

import pymupdf

TITLE = "MASTER SERVICES AGREEMENT"
HEADER = "ACME CONFIDENTIAL"
BODY = (
    "The Supplier shall provide the Services described in each Statement of Work "
    "with reasonable skill and care, and in accordance with good industry practice. "
    "Either party may terminate this Agreement for material breach that is not "
    "remedied within thirty days of written notice."
)
TABLE = [
    ["Milestone", "Due", "Fee"],
    ["Kick-off", "Week 1", "10,000"],
    ["Go-live", "Week 12", "40,000"],
]


def contract_pdf(pages: int = 3) -> bytes:
    """A digital (text-layer) contract:

    page 1  title, "1. DEFINITIONS" heading, paragraph, "(a)" list item
    page 2  "8.3 Notice Period" heading, paragraph, a ruled 3x3 table
    page 3  paragraph and one embedded 300x200 image
    every page: running header and "Page n of N" footer
    """
    doc = pymupdf.open()
    for n in range(1, pages + 1):
        page = doc.new_page()  # A4-ish default: 595 x 842 points
        page.insert_text((72, 30), HEADER, fontsize=8, fontname="helv")
        page.insert_text((250, 825), f"Page {n} of {pages}", fontsize=8, fontname="helv")
        if n == 1:
            page.insert_text((72, 100), TITLE, fontsize=18, fontname="hebo")
            page.insert_text((72, 150), "1. DEFINITIONS", fontsize=12, fontname="hebo")
            page.insert_textbox(pymupdf.Rect(72, 165, 523, 260), BODY, fontsize=10)
            page.insert_textbox(
                pymupdf.Rect(72, 280, 523, 320),
                "(a) the Supplier shall maintain insurance with a reputable insurer;",
                fontsize=10,
            )
        elif n == 2:
            page.insert_text((72, 100), "8.3 Notice Period", fontsize=12, fontname="hebo")
            page.insert_textbox(pymupdf.Rect(72, 115, 523, 210), BODY, fontsize=10)
            _draw_table(page, top=260)
        else:
            page.insert_textbox(pymupdf.Rect(72, 90, 523, 190), BODY, fontsize=10)
            pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 300, 200), False)
            pix.set_rect(pix.irect, (200, 40, 40))
            page.insert_image(pymupdf.Rect(72, 250, 372, 450), pixmap=pix)
    doc.set_metadata({"title": "MSA - Acme", "author": "Legal"})
    return doc.tobytes()


def _draw_table(page: pymupdf.Page, top: float) -> None:
    """Ruled table: every cell has a drawn border, like most contract tables."""
    col_w, row_h, left = 150, 22, 72
    for r, row in enumerate(TABLE):
        for c, value in enumerate(row):
            cell = pymupdf.Rect(
                left + c * col_w, top + r * row_h, left + (c + 1) * col_w, top + (r + 1) * row_h
            )
            page.draw_rect(cell, color=(0, 0, 0), width=0.8)
            page.insert_text((cell.x0 + 4, cell.y1 - 7), value, fontsize=9)


def scanned_pdf(text_lines: tuple[str, ...] = ("TERMINATION", BODY)) -> bytes:
    """A single page that is only an image of text — what a scanner produces.

    The text is drawn on a scratch page, rendered to pixels, and the pixels
    are placed on a new page, so the result has no text layer at all.
    """
    scratch = pymupdf.open()
    src = scratch.new_page()
    src.insert_text((72, 100), text_lines[0], fontsize=22, fontname="hebo")
    src.insert_textbox(pymupdf.Rect(72, 130, 523, 400), " ".join(text_lines[1:]), fontsize=14)
    pix = src.get_pixmap(dpi=200)

    doc = pymupdf.open()
    page = doc.new_page(width=src.rect.width, height=src.rect.height)
    page.insert_image(page.rect, pixmap=pix)
    return doc.tobytes()


def encrypted_pdf(user_password: str = "open-sesame", owner_password: str = "owner") -> bytes:  # noqa: S107
    """user_password="" gives an owner-only (restrictions-only) PDF that opens freely."""
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 100), "Secret terms", fontsize=12)
    return doc.tobytes(
        encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw=user_password, owner_pw=owner_password
    )
