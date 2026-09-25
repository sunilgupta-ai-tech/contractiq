"""
Table extraction with pdfplumber.

Why pdfplumber for tables
-------------------------
Contract tables (fee schedules, SLA credits, payment milestones) are usually
drawn with ruling lines. pdfplumber's "lines" strategy rebuilds the cell grid
from those vector lines, which is far more reliable than guessing columns
from text positions. We deliberately do not use its "text" strategy: on
ordinary prose it invents tables out of aligned words.

Only pages that have a real text layer are scanned for tables. On scanned
pages there are no vector lines to find, and pdfplumber would waste time.
"""

from __future__ import annotations

import io
from collections.abc import Iterable

import pdfplumber

from app.document_processing.parser import Table
from app.document_processing.tables import clean_rows, is_real_table

_TABLE_SETTINGS = {"vertical_strategy": "lines", "horizontal_strategy": "lines"}


def extract_tables(data: bytes, page_numbers: Iterable[int]) -> dict[int, list[Table]]:
    """Return {page_number (1-based): [Table, ...]} for the requested pages.

    pdfplumber's coordinates are PDF points with a top-left origin — the same
    space PyMuPDF uses — so bboxes line up with text blocks without conversion.
    """
    wanted = sorted(set(page_numbers))
    result: dict[int, list[Table]] = {}
    if not wanted:
        return result
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for number in wanted:
            page = pdf.pages[number - 1]
            tables: list[Table] = []
            for found in page.find_tables(table_settings=_TABLE_SETTINGS):
                rows = clean_rows(found.extract())
                if is_real_table(rows):
                    x0, top, x1, bottom = (float(v) for v in found.bbox)
                    tables.append(Table(bbox=(x0, top, x1, bottom), rows=rows))
            if tables:
                result[number] = tables
            # pdfplumber caches every page's parsed objects; release them as we
            # go so a 500-page contract doesn't hold them all in memory.
            page.close()
    return result
