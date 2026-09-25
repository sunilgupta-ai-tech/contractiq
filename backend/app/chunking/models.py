"""
Chunk data model.

Two levels (small-to-big retrieval)
-----------------------------------
* CHILD chunks are small (about one clause). They are embedded and searched,
  because a small, focused chunk matches a specific question far better than
  a whole section does.
* PARENT chunks are whole sections. They are *not* searched; when a child
  matches, its parent is what the LLM reads, so the answer sees the
  surrounding clauses (definitions, exceptions, "subject to 8.4 ...").

Every child has `parent_id`. Tables are CHILD chunks of type TABLE whose text
is markdown, so rows and columns survive into the prompt.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

# Fixed namespace so the same (version, level, position) always yields the
# same chunk ID. Re-processing a version therefore *replaces* its points in
# Qdrant (Phase 6) instead of adding duplicates.
CHUNK_ID_NAMESPACE = uuid.UUID("5b1f0f5e-6c1c-4c7a-9a5e-2f0c1e7d9a41")


class ChunkLevel(StrEnum):
    PARENT = "parent"
    CHILD = "child"


class ChunkType(StrEnum):
    TEXT = "text"
    TABLE = "table"
    # IMAGE_CAPTION = "image_caption" is added in Phase 9 (multimodal).


@dataclass
class SourceRegion:
    """Where on a page a chunk's text came from, for citation highlighting.

    For a clause split into several chunks, each chunk lists the whole source
    blocks it drew from (block-level precision, not character-level).
    """

    page: int
    bbox: tuple[float, float, float, float]


@dataclass
class Chunk:
    id: str
    level: ChunkLevel
    chunk_type: ChunkType
    ordinal: int  # position among chunks of the same level, in reading order
    text: str  # clean text: shown to users and quoted in citations
    # What gets embedded: `text` prefixed with the heading path. Empty for
    # parents (they are never embedded).
    embedding_text: str
    token_count: int
    parent_id: str | None  # set on children
    # Structure. `section`/`clause` are the numbers ("8", "8.3") when the
    # contract numbers them; titles hold the words ("Termination").
    section: str | None
    section_title: str | None
    clause: str | None
    clause_title: str | None
    clauses: list[str]  # every clause number covered (merged small clauses)
    heading_path: list[str]  # e.g. ["Master Services Agreement", "8. Termination", ...]
    page_start: int
    page_end: int
    regions: list[SourceRegion] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Chunk:
        return cls(
            **{
                **data,
                "level": ChunkLevel(data["level"]),
                "chunk_type": ChunkType(data["chunk_type"]),
                "regions": [
                    SourceRegion(page=r["page"], bbox=tuple(r["bbox"])) for r in data["regions"]
                ],
            }
        )


def chunk_id(version_id: str, level: ChunkLevel, ordinal: int) -> str:
    return str(uuid.uuid5(CHUNK_ID_NAMESPACE, f"{version_id}:{level.value}:{ordinal}"))
