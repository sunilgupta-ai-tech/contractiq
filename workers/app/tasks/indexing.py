"""Index maintenance jobs (Phase 6): delete a document version's vectors
when a document is deleted, and rebuild indexes."""

from __future__ import annotations

from typing import Any


async def delete_document_vectors(
    ctx: dict[str, Any], tenant_id: str, document_id: str
) -> dict[str, Any]:
    raise NotImplementedError("Phase 6")
