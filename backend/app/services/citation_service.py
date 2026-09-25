"""
Turn the model's [n] markers into verified citations.

The model cites evidence blocks by number ("... 60 days [3]."). Before the
answer reaches the user:

  1. Every marker is checked against the blocks actually sent. A number the
     model invented ([9] when only 6 blocks exist) is removed — a citation
     must always point at text the user can open.
  2. Valid markers are renumbered 1..k in order of first appearance, so the
     answer reads [1], [2], [3] rather than [4], [1], [6].
  3. Each citation is resolved to document / version / page / section /
     clause and a short quote from the matched chunk.

Also reports `cited_fraction`: the share of answer sentences that carry at
least one valid citation — a cheap groundedness signal (Phase 11 adds a
proper evidence check).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.rag.types import Citation, EvidenceBlock

# "[3]", "[1, 4]", "[2][5]" (the last is two markers)
_MARKER = re.compile(r"\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\]")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
QUOTE_CHARS = 300


@dataclass
class CitedAnswer:
    text: str
    citations: list[Citation]
    cited_fraction: float


def resolve_citations(answer: str, blocks: list[EvidenceBlock]) -> CitedAnswer:
    by_number = {b.number: b for b in blocks}
    renumber: dict[int, int] = {}  # model's block number -> displayed index

    def replace(match: re.Match[str]) -> str:
        numbers = [int(n) for n in re.split(r"\s*,\s*", match.group(1))]
        shown = []
        for number in numbers:
            if number not in by_number:
                continue  # invented reference: drop it
            renumber.setdefault(number, len(renumber) + 1)
            shown.append(f"[{renumber[number]}]")
        return "".join(shown)

    text = _MARKER.sub(replace, answer)
    text = re.sub(r"[ \t]+([.,;:])", r"\1", text).strip()  # tidy space left by removed markers

    citations = [
        _citation(index, by_number[number])
        for number, index in sorted(renumber.items(), key=lambda item: item[1])
    ]
    return CitedAnswer(text=text, citations=citations, cited_fraction=_cited_fraction(text))


def _citation(index: int, block: EvidenceBlock) -> Citation:
    chunk = block.primary
    quote = " ".join(chunk.text.split())
    if len(quote) > QUOTE_CHARS:
        quote = quote[:QUOTE_CHARS].rsplit(" ", 1)[0] + " …"
    return Citation(
        index=index,
        chunk_id=chunk.chunk_id,
        document_id=chunk.document_id,
        document_title=chunk.document_title,
        version_id=chunk.version_id,
        version_label=chunk.version_label,
        page=chunk.page,
        page_end=chunk.page_end,
        section=chunk.section,
        section_title=chunk.section_title,
        clause=chunk.clause,
        clause_title=chunk.clause_title,
        quote=quote,
        score=round(chunk.rerank_score if chunk.rerank_score is not None else chunk.score, 4),
        regions=chunk.regions,
        clauses=chunk.clauses,
    )


def _cited_fraction(text: str) -> float:
    sentences = [s for s in _SENTENCE.split(text) if len(s.strip()) > 3]
    if not sentences:
        return 0.0
    cited = sum(1 for s in sentences if re.search(r"\[\d+\]", s))
    return round(cited / len(sentences), 2)
