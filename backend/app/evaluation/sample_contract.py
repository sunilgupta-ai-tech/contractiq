"""
A synthetic Master Services Agreement for the built-in golden dataset.

Generated in code (PyMuPDF) rather than committed as a binary PDF, so the
evaluation is reproducible anywhere, every fact the dataset asks about is
readable right here, and no client contract is ever needed to test the
pipeline. It exercises what real contracts do: a title, a preamble,
numbered sections with inline clause numbers, a ruled fee table, and a
running header and "Page n of N" footer that must not leak into answers.
"""

from __future__ import annotations

import pymupdf

TITLE = "MASTER SERVICES AGREEMENT"
HEADER = "NORTHWIND / CONTOSO - CONFIDENTIAL"

PREAMBLE = (
    "This Master Services Agreement is made on 15 March 2025 between Northwind Traders Limited "
    '(the "Customer") and Contoso Cloud Services Private Limited (the "Supplier").'
)

SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "1. DEFINITIONS",
        (
            '1.1 "Services" means the cloud hosting and support services described in Schedule 1.',
            '1.2 "Fees" means the charges set out in Schedule 2 and in clause 5.',
        ),
    ),
    (
        "2. TERM",
        (
            '2.1 This Agreement commences on 1 April 2025 (the "Effective Date") and continues '
            "for an initial term of thirty-six (36) months.",
        ),
    ),
    (
        "3. RENEWAL",
        (
            "3.1 On expiry of the initial term, this Agreement shall automatically renew for "
            "successive periods of twelve (12) months unless either party gives written notice "
            "of non-renewal at least ninety (90) days before the end of the then-current term.",
        ),
    ),
    (
        "4. SERVICE LEVELS",
        (
            "4.1 The Supplier shall ensure that the Services are available 99.9% of the time in "
            "each calendar month, excluding scheduled maintenance notified in advance.",
            "4.2 If availability falls below 99.9% in a month, the Customer is entitled to a "
            "service credit of 5% of the monthly Fees for each full 0.1% shortfall, up to a "
            "maximum of 25% of the monthly Fees.",
        ),
    ),
    (
        "5. FEES AND PAYMENT",
        (
            "5.1 The Customer shall pay each undisputed invoice within forty-five (45) days of "
            "receipt.",
            "5.2 Late payments bear interest at 1.5% per month from the due date until payment.",
            "5.3 The Supplier may increase the Fees once in each contract year on sixty (60) days' "
            "written notice, provided that any increase shall not exceed 5% of the Fees then in "
            "force.",
            "5.4 The milestone Fees are set out in the table below.",
        ),
    ),
    (
        "6. CONFIDENTIALITY",
        (
            "6.1 Each party shall keep the other party's Confidential Information confidential "
            "and shall not disclose it to any third party for a period of five (5) years after "
            "termination of this Agreement.",
        ),
    ),
    (
        "7. DATA PROTECTION",
        (
            "7.1 The Supplier shall process personal data only on the documented instructions of "
            "the Customer.",
            "7.2 The Supplier may engage sub-processors on giving the Customer thirty (30) days' "
            "prior written notice, during which the Customer may object on reasonable data "
            "protection grounds.",
            "7.3 The Supplier shall notify the Customer of any personal data breach within "
            "forty-eight (48) hours of becoming aware of it.",
        ),
    ),
    (
        "8. TERMINATION",
        (
            "8.1 Either party may terminate this Agreement with immediate effect by written "
            "notice if the other party commits a material breach that is not remedied within "
            "thirty (30) days of being notified of it.",
            "8.2 The Customer may terminate this Agreement for convenience on one hundred and "
            "twenty (120) days' written notice to the Supplier.",
            "8.3 On termination, the Supplier shall return all Customer Data to the Customer "
            "within fifteen (15) days.",
        ),
    ),
    (
        "9. LIMITATION OF LIABILITY",
        (
            "9.1 Neither party shall be liable for any indirect or consequential loss.",
            "9.2 Each party's total aggregate liability under this Agreement shall not exceed the "
            "Fees paid in the twelve (12) months preceding the event giving rise to the claim.",
        ),
    ),
    (
        "10. INDEMNITY",
        (
            "10.1 The Supplier shall indemnify the Customer against all losses arising from any "
            "claim that the Services infringe the intellectual property rights of a third party.",
        ),
    ),
    (
        "11. GOVERNING LAW AND DISPUTES",
        (
            "11.1 This Agreement is governed by the laws of India.",
            "11.2 Any dispute shall be referred to arbitration in Mumbai under the Arbitration and "
            "Conciliation Act, 1996, before a sole arbitrator.",
        ),
    ),
    (
        "12. GENERAL",
        (
            "12.1 Neither party may assign or transfer this Agreement without the prior written "
            "consent of the other party.",
        ),
    ),
)

FEE_TABLE = (
    ("Milestone", "Due", "Fee (INR)"),
    ("Onboarding", "Month 1", "1,200,000"),
    ("Migration", "Month 3", "2,500,000"),
    ("Go-live", "Month 6", "3,000,000"),
)

_LEFT, _RIGHT, _BOTTOM = 72.0, 523.0, 780.0
_BODY_SIZE, _LINE = 10.0, 13.0
_CHARS_PER_LINE = 88  # Helvetica 10pt across 451pt, conservatively


def sample_msa_pdf() -> bytes:
    """The sample MSA as PDF bytes (4-5 A4 pages)."""
    doc = pymupdf.open()
    writer = _Writer(doc)
    writer.heading(TITLE, size=16, gap=18)
    writer.paragraph(PREAMBLE)
    for heading, clauses in SECTIONS:
        writer.heading(heading)
        for clause in clauses:
            writer.paragraph(clause)
        if heading.startswith("5."):
            writer.table(FEE_TABLE)
    total = len(doc)
    for number in range(1, total + 1):
        page = doc[number - 1]
        page.insert_text((_LEFT, 30), HEADER, fontsize=8, fontname="helv")
        page.insert_text((250, 825), f"Page {number} of {total}", fontsize=8, fontname="helv")
    doc.set_metadata({"title": "Northwind - Contoso MSA", "author": "Legal"})
    return bytes(doc.tobytes())


class _Writer:
    """Flows headings, paragraphs and a table down A4 pages."""

    def __init__(self, doc: pymupdf.Document) -> None:
        self.doc = doc
        self.page = doc.new_page()
        self.y = 70.0

    def _room(self, height: float) -> None:
        if self.y + height > _BOTTOM:
            self.page = self.doc.new_page()
            self.y = 70.0

    def heading(self, text: str, *, size: float = 12, gap: float = 10) -> None:
        self._room(size + gap + 40)  # keep a heading with the text after it
        self.y += gap
        self.page.insert_text((_LEFT, self.y + size), text, fontsize=size, fontname="hebo")
        self.y += size + 8

    def paragraph(self, text: str) -> None:
        lines = -(-len(text) // _CHARS_PER_LINE)  # ceiling division
        height = lines * _LINE + 8
        self._room(height)
        rect = pymupdf.Rect(_LEFT, self.y, _RIGHT, self.y + height)
        self.page.insert_textbox(rect, text, fontsize=_BODY_SIZE, fontname="helv")
        self.y += height + 4

    def table(self, rows: tuple[tuple[str, ...], ...]) -> None:
        col_w, row_h = 150.0, 22.0
        self._room(row_h * len(rows) + 16)
        top = self.y + 6
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                x0, y0 = _LEFT + c * col_w, top + r * row_h
                cell = pymupdf.Rect(x0, y0, x0 + col_w, y0 + row_h)
                self.page.draw_rect(cell, color=(0, 0, 0), width=0.8)
                self.page.insert_text((cell.x0 + 4, cell.y1 - 7), value, fontsize=9)
        self.y = top + row_h * len(rows) + 12


BUILDERS = {"sample_msa": sample_msa_pdf}
