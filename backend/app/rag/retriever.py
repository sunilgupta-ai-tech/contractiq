"""
The retrieval interface used by the question-answering pipeline (and, in
Phase 8, by agent tools).

The pipeline depends on this Protocol, not on Qdrant: tests plug in an
in-memory retriever, and the production implementation
(services/retrieval_service.RetrievalService) can change search strategy
without touching the pipeline.

Tenant safety is part of the contract: every method takes `tenant_id` and
must never return data of another tenant.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from app.rag.types import RetrievedChunk


class Retriever(Protocol):
    async def retrieve(
        self,
        question: str,
        *,
        tenant_id: str,
        document_ids: Sequence[str] | None,
        version_ids: Sequence[str] | None,
        limit: int,
    ) -> list[RetrievedChunk]:
        """Best-matching child chunks for a question, best first."""
        ...

    async def parents(self, *, tenant_id: str, parent_ids: Sequence[str]) -> dict[str, Any]:
        """Parent (section) payloads by id, for small-to-big context."""
        ...
