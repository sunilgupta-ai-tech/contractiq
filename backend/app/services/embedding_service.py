"""
Batches chunk texts through the configured EmbeddingProvider with retry/backoff, and
caches embeddings by content hash so re-indexing unchanged chunks is free.

Status: interface placeholder — implemented in Phase 6.
"""

from __future__ import annotations


class EmbeddingService:
    """See module docstring. Implemented in Phase 6."""
