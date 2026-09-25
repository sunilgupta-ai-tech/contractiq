"""
Data passed between the steps of the question-answering pipeline.

    RetrievedChunk   one search hit (a child chunk) with its scores
    EvidenceBlock    what the LLM reads: a numbered block of context
    Citation         what the user sees: where a cited statement came from
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RetrievedChunk:
    """A child chunk returned by hybrid search, built from its Qdrant payload."""

    chunk_id: str
    parent_id: str | None
    document_id: str
    document_title: str | None
    version_id: str
    version_label: str
    text: str
    heading_path: list[str]
    section: str | None
    section_title: str | None
    clause: str | None
    clause_title: str | None
    page: int
    page_end: int
    chunk_type: str
    score: float  # fused (RRF) score from Qdrant; higher is better
    rerank_score: float | None = None
    regions: list[dict[str, Any]] = field(default_factory=list)
    # Every clause number in the chunk. Small neighbouring clauses are merged
    # into one chunk (Phase 5), so `clause` is only the first of them.
    clauses: list[str] = field(default_factory=list)

    @classmethod
    def from_payload(cls, payload: dict[str, Any], score: float) -> RetrievedChunk:
        return cls(
            chunk_id=payload["chunk_id"],
            parent_id=payload.get("parent_id"),
            document_id=payload["document_id"],
            document_title=payload.get("document_title"),
            version_id=payload["version_id"],
            version_label=payload.get("version_label", ""),
            text=payload["text"],
            heading_path=payload.get("heading_path") or [],
            section=payload.get("section"),
            section_title=payload.get("section_title"),
            clause=payload.get("clause"),
            clause_title=payload.get("clause_title"),
            page=payload.get("page", 0),
            page_end=payload.get("page_end", payload.get("page", 0)),
            chunk_type=payload.get("chunk_type", "text"),
            score=score,
            regions=payload.get("regions") or [],
            clauses=payload.get("clauses") or [],
        )


@dataclass
class EvidenceBlock:
    """One numbered block of context in the prompt ([1], [2], ...).

    `text` may be the whole parent section (small-to-big), while `matches`
    are the specific chunks that search found inside it. A citation to this
    block points at the best match (its clause and page), because that is
    the passage that actually matched the question.
    """

    number: int
    text: str
    heading: str
    matches: list[RetrievedChunk]

    @property
    def primary(self) -> RetrievedChunk:
        return self.matches[0]


@dataclass
class Citation:
    index: int  # the [n] shown in the answer, 1..k in order of first use
    chunk_id: str
    document_id: str
    document_title: str | None
    version_id: str
    version_label: str
    page: int
    page_end: int
    section: str | None
    section_title: str | None
    clause: str | None
    clause_title: str | None
    quote: str
    score: float
    regions: list[dict[str, Any]] = field(default_factory=list)
    clauses: list[str] = field(default_factory=list)  # all clauses the cited text covers
