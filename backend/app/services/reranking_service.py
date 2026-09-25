"""
Reranker selection. The algorithms live in app/rag/reranker.py; this module
only maps the RERANKER setting to one of them, so services depend on the
`Reranker` protocol rather than a concrete class.
"""

from __future__ import annotations

from app.core.config import Settings
from app.rag.reranker import Reranker, create_reranker


def reranker_for(settings: Settings) -> Reranker:
    return create_reranker(settings.reranker)
