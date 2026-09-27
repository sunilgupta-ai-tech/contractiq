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
from typing import Any

import pdfplumber

from app.document_processing.parser import ParsedPage, Table, TextBlock
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


def extract_text_pages(data: bytes) -> list[ParsedPage]:
    """Fallback reader (Phase 21) for PDFs PyMuPDF cannot open.

    pdfminer (under pdfplumber) tolerates some damaged cross-reference
    tables and unusual encodings that MuPDF rejects. Lines are grouped into
    paragraphs where a vertical gap appears; positions are the text's own,
    so reading order and citations still work. Raises whatever pdfplumber
    raises if it cannot read the file either.
    """
    pages: list[ParsedPage] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for index, page in enumerate(pdf.pages, start=1):
            parsed = ParsedPage(number=index, width=float(page.width), height=float(page.height))
            parsed.blocks = [_block(group) for group in _paragraphs(page.extract_text_lines())]
            pages.append(parsed)
            page.close()
    return pages


def _paragraphs(lines: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Split lines where the gap to the previous line exceeds ~80% of a line's height."""
    groups: list[list[dict[str, Any]]] = []
    for line in (line for line in lines if line["text"].strip()):
        if groups:
            previous = groups[-1][-1]
            height = float(line["bottom"]) - float(line["top"])
            if float(line["top"]) - float(previous["bottom"]) <= height * 0.8:
                groups[-1].append(line)
                continue
        groups.append([line])
    return groups


def _block(lines: list[dict[str, Any]]) -> TextBlock:
    return TextBlock(
        text=" ".join(" ".join(line["text"].split()) for line in lines),
        bbox=(
            min(float(line["x0"]) for line in lines),
            float(lines[0]["top"]),
            max(float(line["x1"]) for line in lines),
            float(lines[-1]["bottom"]),
        ),
    )
