"""
Phase 5 tests: outline detection, segmenting, splitting, merging, tables,
parent/child linking and deterministic IDs.

Most tests build a ParsedDocument by hand (see `_doc`) so each rule is tested
in isolation; the last test runs a generated PDF through Phases 4 and 5.
"""

import pytest

from app.chunking.models import Chunk, ChunkLevel, ChunkType
from app.chunking.splitter import split_pieces, split_sentences
from app.chunking.structure import Piece, build_segments, inline_clause, parse_heading
from app.chunking.tokens import estimate_tokens
from app.document_processing.parser import BlockKind, ParsedDocument, ParsedPage, Table, TextBlock
from app.services.chunking_service import ChunkingOptions, chunk_document
from app.services.pdf_service import PdfOptions, finalize_layout, parse_pdf
from tests import pdf_factory

VERSION = "3f2c1a9e-0000-4000-8000-000000000001"
H, P, L = BlockKind.HEADING, BlockKind.PARAGRAPH, BlockKind.LIST_ITEM
LONG = " ".join(
    f"Sentence {i} explains an obligation of the Supplier in detail." for i in range(80)
)


def _doc(*pages: list[tuple[BlockKind, str]], tables: dict[int, Table] | None = None):
    """Pages of (kind, text) blocks, stacked top to bottom 30pt apart."""
    parsed = []
    for n, blocks in enumerate(pages, start=1):
        page = ParsedPage(number=n, width=595, height=842)
        for i, (kind, text) in enumerate(blocks):
            y = 60 + i * 30
            page.blocks.append(TextBlock(text=text, bbox=(72, y, 520, y + 20), kind=kind))
        if tables and n in tables:
            page.tables.append(tables[n])
        parsed.append(page)
    return ParsedDocument(pages=parsed)


CONTRACT = _doc(
    [
        (H, "MASTER SERVICES AGREEMENT"),
        (P, "This Agreement is made between Acme Ltd. and Beta Inc. on 1 March 2026."),
        (H, "1. DEFINITIONS"),
        (P, "In this Agreement the following terms have the meanings given below."),
        (H, "8. TERMINATION"),
        (P, "8.1 Either party may terminate this Agreement for material breach."),
        (P, "8.2 The Customer may terminate for convenience on ninety days notice."),
        (L, "(a) any accrued fees remain payable;"),
    ],
    [
        (H, "8.3 Notice Period"),
        (P, "Notices must be given in writing to the address set out in Schedule 1."),
    ],
    tables={2: Table(bbox=(72, 200, 520, 260), rows=[["Fee", "Due"], ["10,000", "Q1"]])},
)


# --- Outline rules ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "inside", "number", "title", "level"),
    [
        ("8. TERMINATION", False, "8", "TERMINATION", 1),
        ("8.3 Notice Period", True, "8.3", "Notice Period", 2),
        ("8.3.1 Form of notice", True, "8.3.1", "Form of notice", 3),
        ("ARTICLE 5 - Payment", False, "5", "Payment", 1),
        ("Article IV", False, "IV", "", 1),
        ("Schedule 2 Fees", True, "Schedule 2", "Fees", 1),
        ("Section 4.2 Invoices", True, "4.2", "Invoices", 2),
        ("LIMITATION OF LIABILITY", True, None, "LIMITATION OF LIABILITY", 1),
        ("Notice Period", True, None, "Notice Period", 2),
        ("Notice Period", False, None, "Notice Period", 1),
    ],
)
def test_parse_heading(text, inside, number, title, level):
    heading = parse_heading(text, inside_section=inside)
    assert (heading.number, heading.title, heading.level) == (number, title, level)


def test_inline_clause_needs_a_dotted_number():
    assert inline_clause("8.3 The Supplier shall pay").number == "8.3"
    assert inline_clause("8 weeks after delivery the Supplier ...") is None  # a quantity


def test_segments_follow_the_outline():
    title, segments = build_segments(CONTRACT)
    assert title == "MASTER SERVICES AGREEMENT"  # first unnumbered heading on page 1
    summary = [(s.section, s.clause, s.is_table) for s in segments]
    assert summary == [
        (None, None, False),  # preamble
        ("1", None, False),
        ("8", None, False),  # "8. TERMINATION" heading alone
        ("8", "8.1", False),
        ("8", "8.2", False),  # the (a) list item stays with 8.2
        ("8", "8.3", False),
        ("8", "8.3", True),  # the table, placed under 8.3 by position
    ]
    assert segments[0].section_key == "preamble"
    assert segments[4].pieces[-1].text.startswith("(a)")


# --- Chunks -----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def result():
    return chunk_document(
        CONTRACT, version_id=VERSION, document_title="Acme MSA", options=ChunkingOptions()
    )


def test_small_segments_merge_within_a_section_only(result):
    texts = [c.text for c in result.children if c.chunk_type is ChunkType.TEXT]
    # The bare "8. TERMINATION" heading joins the clauses after it...
    termination = next(t for t in texts if t.startswith("8. TERMINATION"))
    assert "8.1 Either party" in termination and "8.2 The Customer" in termination
    # ...but never crosses into another section.
    assert not any("DEFINITIONS" in t and "TERMINATION" in t for t in texts)


def test_child_metadata_and_embedding_context(result):
    child = next(c for c in result.children if "8.1 Either party" in c.text)
    assert (child.section, child.section_title, child.clause) == ("8", "TERMINATION", "8.1")
    assert child.clauses[:2] == ["8.1", "8.2"]
    assert child.heading_path[:2] == ["Acme MSA", "8 TERMINATION"]
    assert child.embedding_text.startswith("Acme MSA > 8 TERMINATION")
    assert child.embedding_text.endswith(child.text)
    assert child.page_start == 1 and child.regions[0].page == 1


def test_preamble_gets_its_own_path(result):
    preamble = result.children[0]
    assert preamble.section is None and preamble.heading_path == ["Acme MSA", "Preamble"]


def test_table_is_its_own_markdown_chunk(result):
    table = next(c for c in result.children if c.chunk_type is ChunkType.TABLE)
    assert table.text.startswith("| Fee | Due |")
    assert table.clause == "8.3" and table.page_start == 2


def test_every_child_links_to_a_parent_of_its_section(result):
    parents = {p.id: p for p in result.parents}
    assert [p.section for p in result.parents] == [None, "1", "8"]
    for child in result.children:
        assert child.parent_id in parents
        assert parents[child.parent_id].section == child.section
    assert all(p.embedding_text == "" for p in result.parents)  # parents aren't searched
    termination = parents[result.children[-1].parent_id]
    assert "8.1 Either party" in termination.text and "| Fee | Due |" in termination.text


def test_chunk_ids_are_deterministic_per_version(result):
    again = chunk_document(
        CONTRACT, version_id=VERSION, document_title="Acme MSA", options=ChunkingOptions()
    )
    assert [c.id for c in again.chunks] == [c.id for c in result.chunks]
    other = chunk_document(
        CONTRACT, version_id="another-version", document_title=None, options=ChunkingOptions()
    )
    assert not {c.id for c in other.chunks} & {c.id for c in result.chunks}


def test_long_clause_is_split_with_overlap_and_within_limits():
    doc = _doc([(H, "5. SERVICES"), (P, "5.1 " + LONG)])
    options = ChunkingOptions(max_tokens=200, overlap_tokens=40, parent_max_tokens=600)
    result = chunk_document(doc, version_id=VERSION, document_title=None, options=options)
    children = result.children
    assert len(children) > 3
    assert all(c.token_count <= 200 for c in children)
    assert all(c.clause == "5.1" for c in children)  # every piece keeps its clause
    # Consecutive pieces share their boundary sentence(s).
    first_end = children[0].text.rsplit("Sentence", 1)[1]
    assert first_end in children[1].text
    # A section too long for one parent is split into several parents.
    assert len(result.parents) > 1 and all(p.token_count <= 600 for p in result.parents)


def test_long_table_split_by_rows_repeats_header():
    rows = [["Milestone", "Fee"]] + [[f"Milestone number {i}", f"{i},000"] for i in range(60)]
    doc = _doc([(H, "SCHEDULE 1 FEES")], tables={1: Table(bbox=(72, 100, 520, 700), rows=rows)})
    options = ChunkingOptions(max_tokens=120)
    result = chunk_document(doc, version_id=VERSION, document_title=None, options=options)
    tables = [c for c in result.children if c.chunk_type is ChunkType.TABLE]
    assert len(tables) > 1
    assert all(t.text.startswith("| Milestone | Fee |") for t in tables)


def test_chunk_json_roundtrip(result):
    for chunk in result.chunks:
        assert Chunk.from_dict(chunk.to_dict()) == chunk


# --- Splitter helpers --------------------------------------------------------------------


def test_sentences_ignore_legal_abbreviations():
    text = "Acme Ltd. shall pay the fees, e.g. licence fees. See Schedule A. The Customer agrees."
    assert split_sentences(text) == [
        "Acme Ltd. shall pay the fees, e.g. licence fees.",
        "See Schedule A. The Customer agrees.",
    ]


def test_single_huge_sentence_is_cut_between_words():
    words = "word " * 1000
    windows = split_pieces([Piece(words, 1, (0, 0, 1, 1))], max_tokens=100, overlap_tokens=0)
    assert len(windows) > 5 and all(estimate_tokens(w.text) <= 100 for w in windows)


# --- Phase 4 -> Phase 5 on a real (generated) PDF ------------------------------------------


def test_generated_contract_pdf_end_to_end():
    parsed = parse_pdf(pdf_factory.contract_pdf(), PdfOptions()).document
    finalize_layout(parsed)
    result = chunk_document(
        parsed, version_id=VERSION, document_title=None, options=ChunkingOptions()
    )
    children = result.children
    # Title detected from the PDF becomes the root of every heading path.
    assert all(c.heading_path[0] == pdf_factory.TITLE for c in children)
    assert any(c.section == "1" and "DEFINITIONS" in c.text for c in children)
    notice = next(c for c in children if c.clause == "8.3" and c.chunk_type is ChunkType.TEXT)
    assert notice.clause_title == "Notice Period"
    assert any(c.chunk_type is ChunkType.TABLE and "Kick-off" in c.text for c in children)
    # Running headers/footers never leak into chunks.
    assert not any(pdf_factory.HEADER in c.text or "Page 1 of 3" in c.text for c in result.chunks)
    assert {c.level for c in result.chunks} == {ChunkLevel.PARENT, ChunkLevel.CHILD}
