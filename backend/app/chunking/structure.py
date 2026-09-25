"""
Contract structure: turn a ParsedDocument's labelled blocks into *segments*.

A segment is a run of content that belongs to one place in the contract's
outline — e.g. everything under "8.3 Notice Period" until the next heading or
numbered clause. Segments are the raw material for chunks: chunk boundaries
never cut across them, so a chunk never mixes two unrelated clauses (unless
chunking_service deliberately merges tiny neighbours in the same section).

How the outline is recognised
-----------------------------
Contracts announce structure with numbering far more reliably than with
fonts, so numbering decides the level:

    "8. TERMINATION" / "ARTICLE 8" / "Schedule 2"   level 1  -> section
    "8.3 Notice Period"                             level 2  -> clause
    "8.3.1 ..."                                     level 3  -> sub-clause
    "TERMINATION" (unnumbered, all caps)            level 1  -> section
    "Notice Period" (unnumbered, inside a section)  level 2  -> clause title

Many contracts put the clause number at the start of the paragraph instead
of on its own heading line ("8.3 The Supplier shall ..."). Such a paragraph
also starts a new clause. Only dotted numbers ("8.3") count here: a bare
"8 " at the start of a sentence is too often a quantity ("8 weeks after ...").

The first unnumbered heading on page 1, before any other content, is taken
as the document title (e.g. "MASTER SERVICES AGREEMENT"), not as a section.
Content before the first section (parties, recitals) is the "preamble".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.document_processing.parser import (
    NON_CONTENT_KINDS,
    BlockKind,
    ParsedDocument,
    ParsedPage,
    Table,
    TextBlock,
)

PREAMBLE_KEY = "preamble"

_NUMBERED = re.compile(r"^(?P<num>\d{1,3}(?:\.\d{1,3}){0,3})\.?\s+(?P<title>.*)$", re.DOTALL)
_NAMED = re.compile(
    r"^(?P<kind>article|section|clause|schedule|annex|appendix|exhibit)\s+"
    r"(?P<num>\d{1,3}(?:\.\d{1,3}){0,3}|[ivxlc]+|[a-z])\b[.:\-–\s]*(?P<title>.*)$",
    re.IGNORECASE | re.DOTALL,
)
# A paragraph that starts with a dotted clause number: "8.3 The Supplier ..."
_INLINE_CLAUSE = re.compile(r"^(?P<num>\d{1,3}(?:\.\d{1,3}){1,3})\.?\s+\S")


@dataclass(frozen=True)
class Heading:
    number: str | None  # "8", "8.3", "Schedule 2"; None when unnumbered
    title: str  # the words after the number ("Termination"); may be empty
    level: int  # 1 = section, 2 = clause, 3+ = sub-clause

    @property
    def label(self) -> str:
        """How the heading appears in a heading path: '8.3 Notice Period'."""
        return " ".join(p for p in (self.number, self.title) if p)


@dataclass
class Piece:
    """One source block (or table) inside a segment."""

    text: str
    page: int
    bbox: tuple[float, float, float, float]


@dataclass
class Segment:
    is_table: bool
    section_key: str  # groups segments into sections (parent chunks)
    section: str | None
    section_title: str | None
    clause: str | None
    clause_title: str | None
    heading_path: list[str]  # excludes the document title (added by the service)
    pieces: list[Piece] = field(default_factory=list)
    table: Table | None = None  # set when is_table

    @property
    def text(self) -> str:
        if self.table is not None:
            return self.table.to_markdown()
        return "\n\n".join(p.text for p in self.pieces)


def parse_heading(text: str, *, inside_section: bool = False) -> Heading:
    """Work out the number, title and outline level of a heading's text."""
    text = " ".join(text.split())
    if m := _NAMED.match(text):
        kind, num = m["kind"].capitalize(), m["num"]
        # "Section 4.2" / "Clause 4.2": level from the dots, like "4.2".
        if kind in ("Section", "Clause") and "." in num:
            return Heading(number=num, title=m["title"].strip(), level=num.count(".") + 1)
        # Articles and schedules/annexes/exhibits are top-level parts.
        number = num if kind in ("Section", "Clause", "Article") else f"{kind} {num}"
        return Heading(number=number, title=m["title"].strip(), level=1)
    if m := _NUMBERED.match(text):
        num = m["num"]
        return Heading(number=num, title=m["title"].strip(), level=num.count(".") + 1)
    # Unnumbered: all caps reads as a section; otherwise, if we are already
    # inside a section, it is a sub-heading (a clause without a number).
    letters = [c for c in text if c.isalpha()]
    all_caps = bool(letters) and all(c.isupper() for c in letters)
    return Heading(number=None, title=text, level=2 if inside_section and not all_caps else 1)


def inline_clause(text: str) -> Heading | None:
    """The clause a numbered paragraph starts ("8.3 The Supplier ..." -> 8.3)."""
    m = _INLINE_CLAUSE.match(text)
    if not m:
        return None
    num = m["num"]
    return Heading(number=num, title="", level=num.count(".") + 1)


@dataclass
class _Outline:
    """The stack of headings currently "open" while walking the document."""

    stack: list[Heading] = field(default_factory=list)

    def enter(self, heading: Heading) -> None:
        # A heading closes every open heading at its level or deeper.
        while self.stack and self.stack[-1].level >= heading.level:
            self.stack.pop()
        self.stack.append(heading)

    def new_segment(self, *, is_table: bool = False) -> Segment:
        section = self.stack[0] if self.stack and self.stack[0].level == 1 else None
        deeper = [h for h in self.stack if h.level >= 2]
        clause = deeper[-1] if deeper else None
        return Segment(
            is_table=is_table,
            section_key=(section.label or PREAMBLE_KEY) if section else PREAMBLE_KEY,
            section=section.number if section else None,
            section_title=(section.title or None) if section else None,
            clause=clause.number if clause else None,
            clause_title=(clause.title or None) if clause else None,
            heading_path=[h.label for h in self.stack if h.label],
        )


def build_segments(doc: ParsedDocument) -> tuple[str | None, list[Segment]]:
    """Walk every content block in reading order and group it into segments.

    Returns (document title found in the PDF or None, segments in order).
    """
    outline = _Outline()
    segments: list[Segment] = []
    current: Segment | None = None
    title: str | None = None
    seen_content = False

    def flush() -> None:
        nonlocal current
        if current is not None and current.pieces:
            segments.append(current)
        current = None

    for page in doc.pages:
        for item in _page_items(page):
            if isinstance(item, Table):
                # A table is its own segment, at its place in the outline.
                flush()
                table_seg = outline.new_segment(is_table=True)
                table_seg.table = item
                table_seg.pieces.append(Piece(item.to_markdown(), page.number, item.bbox))
                segments.append(table_seg)
                seen_content = True
                continue

            block = item
            piece = Piece(block.text, page.number, block.bbox)
            if block.kind is BlockKind.HEADING:
                heading = parse_heading(block.text, inside_section=bool(outline.stack))
                if title is None and not seen_content and page.number == 1 and not heading.number:
                    title = heading.title
                    continue
                outline.enter(heading)
                flush()
                current = outline.new_segment()
                current.pieces.append(piece)  # keep the heading line in the chunk text
            elif (inline := inline_clause(block.text)) is not None:
                outline.enter(inline)
                flush()
                current = outline.new_segment()
                current.pieces.append(piece)
            else:
                if current is None:
                    current = outline.new_segment()
                current.pieces.append(piece)
            seen_content = True
    flush()
    return title, segments


def _page_items(page: ParsedPage) -> list[TextBlock | Table]:
    """A page's content in reading order: text blocks (minus headers, footers
    and table-cell text) with each table inserted where it sits vertically."""
    blocks = [b for b in page.blocks if b.kind not in NON_CONTENT_KINDS]
    tables = sorted(page.tables, key=lambda t: t.bbox[1])
    items: list[TextBlock | Table] = []
    for block in blocks:
        while tables and tables[0].bbox[1] <= block.bbox[1]:
            items.append(tables.pop(0))
        items.append(block)
    items.extend(tables)
    return items
