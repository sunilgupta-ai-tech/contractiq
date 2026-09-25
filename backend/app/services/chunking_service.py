"""
Contract-aware chunking: Document -> Section -> Clause -> Sub-clause -> Chunk. Clause
headings (e.g. '8.3 Notice Period') bound chunks; parent/child IDs enable small-to-big
retrieval.

Status: interface placeholder — implemented in Phase 5.
"""

from __future__ import annotations


class ChunkingService:
    """See module docstring. Implemented in Phase 5."""
