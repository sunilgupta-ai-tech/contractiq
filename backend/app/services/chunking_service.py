"""
Contract-aware chunking: ParsedDocument -> parent and child Chunks.

Steps (each is explained where it happens below):

    1. build_segments()      outline-aware segments (see chunking/structure.py)
    2. _merge_small()        tiny neighbouring segments in one section are merged
    3. children              each merged group -> 1+ CHILD chunks (split if long);
                             each table -> its own TABLE child (split by rows if long)
    4. parents               each section -> 1+ PARENT chunks (split if very long)
    5. linking               every child gets the id of the parent holding its text

Why not fixed-size chunks
-------------------------
A fixed 500-token window routinely starts halfway through clause 8.2 and ends
halfway through 8.4. The retrieved text then mixes obligations from different
clauses, and a citation to "8.3" is wrong half the time. Cutting at the
contract's own boundaries keeps each chunk about one thing and makes
section/clause metadata exact.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from app.chunking.models import Chunk, ChunkLevel, ChunkType, SourceRegion, chunk_id
from app.chunking.splitter import split_pieces
from app.chunking.structure import PREAMBLE_KEY, Piece, Segment, build_segments
from app.chunking.tokens import estimate_tokens
from app.core.config import Settings
from app.document_processing.parser import ParsedDocument, Table

# Bump when chunking rules change, so stored chunks.json files record which
# rules produced them (and stale ones can be found and re-chunked).
CHUNKER_VERSION = 1


@dataclass(frozen=True)
class ChunkingOptions:
    """Sizes in *estimated* tokens (see chunking/tokens.py).

    max_tokens     child chunk ceiling. ~400 keeps a chunk to one clause in
                   most contracts while fitting every common embedding model.
    min_tokens     segments smaller than this are merged with a neighbour
                   (a bare heading, or "8.2 [Intentionally left blank]").
    overlap_tokens carried between consecutive chunks of one long clause.
    parent_max     parent (section) ceiling: what the LLM reads per hit.
    """

    max_tokens: int = 400
    min_tokens: int = 60
    overlap_tokens: int = 50
    parent_max_tokens: int = 1600

    @classmethod
    def from_settings(cls, settings: Settings) -> ChunkingOptions:
        return cls(
            max_tokens=settings.chunk_max_tokens,
            min_tokens=settings.chunk_min_tokens,
            overlap_tokens=settings.chunk_overlap_tokens,
            parent_max_tokens=settings.chunk_parent_max_tokens,
        )


@dataclass
class ChunkingResult:
    chunks: list[Chunk] = field(default_factory=list)

    @property
    def children(self) -> list[Chunk]:
        return [c for c in self.chunks if c.level is ChunkLevel.CHILD]

    @property
    def parents(self) -> list[Chunk]:
        return [c for c in self.chunks if c.level is ChunkLevel.PARENT]

    def to_dict(self, options: ChunkingOptions) -> dict[str, object]:
        """The chunks.json payload: chunks plus the settings that made them."""
        return {
            "chunker_version": CHUNKER_VERSION,
            "options": options.__dict__,
            "chunks": [c.to_dict() for c in self.chunks],
        }


def chunk_document(
    doc: ParsedDocument,
    *,
    version_id: str,
    document_title: str | None,
    options: ChunkingOptions,
) -> ChunkingResult:
    """Chunk one document version. Deterministic: same input -> same chunk IDs."""
    pdf_title, segments = build_segments(doc)
    # The user-facing title (from the upload) wins over the PDF's own heading.
    title = (document_title or pdf_title or "").strip() or None

    parents, parent_of_segment = _build_parents(segments, version_id, title, options)
    children = _build_children(segments, parent_of_segment, version_id, title, options)
    return ChunkingResult(chunks=parents + children)


# --- Step 2: merge tiny segments ---------------------------------------------------------


def _merge_small(segments: list[Segment], options: ChunkingOptions) -> list[list[int]]:
    """Group consecutive *text* segment indexes of the same section so that no
    group is below `min_tokens` when a neighbour can absorb it.

    A tiny segment always joins the *following* segment of its section — a
    heading belongs with the text after it, even if that text is long (the
    splitter then cuts the group, and the heading lands in the first piece).
    A tiny segment at the end of a section joins the previous group if that
    stays within `max_tokens`, otherwise it stands alone.
    """
    groups: list[list[int]] = []
    pending: list[int] = []  # tiny segments waiting to join the next one
    last_key: str | None = None

    def size(indexes: Iterable[int]) -> int:
        return sum(estimate_tokens(segments[i].text) for i in indexes)

    for index, seg in enumerate(segments):
        if seg.is_table:
            continue
        if seg.section_key != last_key and pending:
            _attach_leftover(groups, pending, segments, size, options)
            pending = []
        last_key = seg.section_key
        candidate = [*pending, index]
        if size(candidate) < options.min_tokens:
            pending = candidate
            continue
        groups.append(candidate)
        pending = []
    if pending:
        _attach_leftover(groups, pending, segments, size, options)
    return groups


def _attach_leftover(
    groups: list[list[int]],
    pending: list[int],
    segments: list[Segment],
    size: Callable[[Iterable[int]], int],
    options: ChunkingOptions,
) -> None:
    """Tiny segments at the end of a section: append to the previous group of
    the same section if it fits, otherwise keep them as their own group."""
    if (
        groups
        and segments[groups[-1][0]].section_key == segments[pending[0]].section_key
        and size(groups[-1] + pending) <= options.max_tokens
    ):
        groups[-1].extend(pending)
    else:
        groups.append(list(pending))


# --- Step 3: children ------------------------------------------------------------------


def _build_children(
    segments: list[Segment],
    parent_of_segment: dict[int, str],
    version_id: str,
    title: str | None,
    options: ChunkingOptions,
) -> list[Chunk]:
    # Text groups and tables, back in reading order (by first segment index).
    units: list[tuple[int, list[int]]] = [(g[0], g) for g in _merge_small(segments, options)]
    units += [(i, [i]) for i, s in enumerate(segments) if s.is_table]
    units.sort(key=lambda u: u[0])

    children: list[Chunk] = []
    for first, group in units:
        segs = [segments[i] for i in group]
        # Structure metadata comes from the first segment that names a
        # clause (a merged heading-only segment usually doesn't).
        lead = next((s for s in segs if s.clause), segs[0])
        clauses = list(dict.fromkeys(s.clause for s in segs if s.clause))
        if segs[0].is_table:
            assert segs[0].table is not None
            windows = [(text, [0]) for text in _split_table(segs[0].table, options.max_tokens)]
            pieces = segs[0].pieces
            chunk_type = ChunkType.TABLE
        else:
            pieces = [p for s in segs for p in s.pieces]
            split = split_pieces(
                pieces, max_tokens=options.max_tokens, overlap_tokens=options.overlap_tokens
            )
            windows = [(w.text, w.source_indexes) for w in split]
            chunk_type = ChunkType.TEXT
        path = _path(title, lead)
        for text, sources in windows:
            used = [pieces[i] for i in sources]
            ordinal = len(children)
            children.append(
                Chunk(
                    id=chunk_id(version_id, ChunkLevel.CHILD, ordinal),
                    level=ChunkLevel.CHILD,
                    chunk_type=chunk_type,
                    ordinal=ordinal,
                    text=text,
                    # The heading path gives the embedding context the chunk
                    # text lacks: "within the notice period" is ambiguous
                    # alone, clear under "8. Termination > 8.3 Notice Period".
                    embedding_text=" > ".join(path) + "\n\n" + text if path else text,
                    token_count=estimate_tokens(text),
                    parent_id=parent_of_segment.get(first),
                    section=lead.section,
                    section_title=lead.section_title,
                    clause=lead.clause,
                    clause_title=lead.clause_title,
                    clauses=clauses,
                    heading_path=path,
                    page_start=min(p.page for p in used),
                    page_end=max(p.page for p in used),
                    regions=_regions(used),
                )
            )
    return children


def _split_table(table: Table, max_tokens: int) -> list[str]:
    """A long table is split by rows, repeating the header row in every part,
    so each chunk is still a readable table with its column names."""
    if estimate_tokens(table.to_markdown()) <= max_tokens or len(table.rows) <= 2:
        return [table.to_markdown()]
    header, body = table.rows[0], table.rows[1:]
    parts: list[str] = []
    batch: list[list[str]] = []
    for row in body:
        candidate = Table(bbox=table.bbox, rows=[header, *batch, row]).to_markdown()
        if batch and estimate_tokens(candidate) > max_tokens:
            parts.append(Table(bbox=table.bbox, rows=[header, *batch]).to_markdown())
            batch = []
        batch.append(row)
    parts.append(Table(bbox=table.bbox, rows=[header, *batch]).to_markdown())
    return parts


# --- Step 4: parents ---------------------------------------------------------------------


def _build_parents(
    segments: list[Segment], version_id: str, title: str | None, options: ChunkingOptions
) -> tuple[list[Chunk], dict[int, str]]:
    """One parent per section; a section longer than `parent_max_tokens` is
    split at segment boundaries into several parents (a single giant segment
    is split further by the splitter)."""
    parents: list[Chunk] = []
    parent_of_segment: dict[int, str] = {}

    for section_indexes in _sections(segments):
        batch: list[int] = []
        for index in section_indexes:
            if batch and _tokens(segments, [*batch, index]) > options.parent_max_tokens:
                _emit_parents(
                    parents, parent_of_segment, segments, batch, version_id, title, options
                )
                batch = []
            batch.append(index)
        if batch:
            _emit_parents(parents, parent_of_segment, segments, batch, version_id, title, options)
    return parents, parent_of_segment


def _emit_parents(
    parents: list[Chunk],
    parent_of_segment: dict[int, str],
    segments: list[Segment],
    indexes: list[int],
    version_id: str,
    title: str | None,
    options: ChunkingOptions,
) -> None:
    pieces = [p for i in indexes for p in segments[i].pieces]
    windows = split_pieces(pieces, max_tokens=options.parent_max_tokens, overlap_tokens=0)
    section_segs = [segments[i] for i in indexes]
    first = section_segs[0]
    for window in windows:
        ordinal = len(parents)
        used = [pieces[i] for i in window.source_indexes]
        parent = Chunk(
            id=chunk_id(version_id, ChunkLevel.PARENT, ordinal),
            level=ChunkLevel.PARENT,
            chunk_type=ChunkType.TEXT,
            ordinal=ordinal,
            text=window.text,
            embedding_text="",  # parents are read, never searched
            token_count=estimate_tokens(window.text),
            parent_id=None,
            section=first.section,
            section_title=first.section_title,
            clause=None,
            clause_title=None,
            clauses=list(dict.fromkeys(s.clause for s in section_segs if s.clause)),
            heading_path=_path(title, first)[: 2 if title else 1],
            page_start=min(p.page for p in used),
            page_end=max(p.page for p in used),
            regions=_regions(used),
        )
        parents.append(parent)
        # Only the first window of a giant segment is recorded; its children
        # still land in a parent that contains the start of their text.
        for index in indexes:
            parent_of_segment.setdefault(index, parent.id)


def _sections(segments: list[Segment]) -> list[list[int]]:
    """Segment indexes grouped by consecutive section key, in order."""
    groups: list[list[int]] = []
    for index, seg in enumerate(segments):
        if groups and segments[groups[-1][0]].section_key == seg.section_key:
            groups[-1].append(index)
        else:
            groups.append([index])
    return groups


# --- Helpers -----------------------------------------------------------------------------


def _tokens(segments: list[Segment], indexes: list[int]) -> int:
    return sum(estimate_tokens(segments[i].text) for i in indexes)


def _path(title: str | None, seg: Segment) -> list[str]:
    path = list(seg.heading_path)
    if not path and seg.section_key == PREAMBLE_KEY:
        path = ["Preamble"]
    return [title, *path] if title else path


def _regions(pieces: list[Piece]) -> list[SourceRegion]:
    return [SourceRegion(page=p.page, bbox=p.bbox) for p in pieces]
