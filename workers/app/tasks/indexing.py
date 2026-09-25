"""Index maintenance jobs."""

from __future__ import annotations

from typing import Any

from app.vectorstore.indexing import delete_document_points


async def delete_document_vectors(
    ctx: dict[str, Any], tenant_id: str, document_id: str
) -> dict[str, Any]:
    """Remove every Qdrant point (all versions, parents and children) of one
    document. The API deletes vectors synchronously on DELETE /documents/{id};
    this job exists for asynchronous clean-ups (e.g. retrying after Qdrant
    was unavailable)."""
    resources = ctx["resources"]
    await delete_document_points(
        resources.qdrant,
        resources.settings.qdrant_collection,
        tenant_id=tenant_id,
        document_id=document_id,
    )
    return {"deleted_document": document_id}
