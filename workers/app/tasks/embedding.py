"""
Re-embedding job: re-embed all of a tenant's processed documents with the
currently configured embedding model.

When is this needed?
--------------------
After changing EMBEDDING_PROVIDER / EMBEDDING_MODEL. Vectors from different
models live in different "spaces" and must never be compared, so every
point records its `embedding_model`, and search (Phase 7) only considers
points of the current model. Until a document is re-embedded it is simply
absent from search results — never matched against the wrong vectors.

If EMBEDDING_DIMENSION also changes, the collection itself must change:
set a new QDRANT_COLLECTION first (it is created on startup), then run this
job for every tenant, then delete the old collection. See docs/embeddings.md.

The job reuses each version's chunks.json, so no parsing, OCR or chunking is
repeated, and the per-tenant embedding cache avoids paying for texts that
were embedded with this model before.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from app.core.logging import get_logger, tenant_id_ctx
from app.db.models import Document, DocumentStatus, DocumentVersion

from ..services.pipeline import StageContext, embed_and_index

logger = get_logger("contractiq.worker.embedding")


async def reembed_tenant(ctx: dict[str, Any], tenant_id: str) -> dict[str, Any]:
    """Re-embed and re-index every COMPLETED version of `tenant_id`'s documents.

    Versions are processed one at a time; a failure is logged and counted
    and the job moves on, so one broken document can't block the rest.
    Enqueue with:  await queue.enqueue_job("reembed_tenant", "<tenant uuid>")
    """
    resources = ctx["resources"]
    tenant_id_ctx.set(tenant_id)
    async with resources.db.session_factory() as session:
        rows = (
            await session.execute(
                select(DocumentVersion, Document)
                .join(Document, Document.id == DocumentVersion.document_id)
                .where(
                    DocumentVersion.organization_id == uuid.UUID(tenant_id),
                    DocumentVersion.status == DocumentStatus.COMPLETED,
                )
                .order_by(DocumentVersion.created_at)
            )
        ).all()

    done, failed = 0, 0
    for version, document in rows:
        stage_ctx = StageContext(
            tenant_id=tenant_id,
            document_id=str(document.id),
            version_id=str(version.id),
            storage_key=version.storage_key,
            resources=resources,
            document_title=document.title,
            version_label=version.label,
            contract_type=document.contract_type.value,
            is_latest_version=document.current_version_id == version.id,
        )
        try:
            await embed_and_index(stage_ctx)
            done += 1
        except Exception:  # noqa: BLE001 — continue with the other documents
            failed += 1
            logger.exception("reembed_failed", extra={"version_id": str(version.id)})
    logger.info("reembed_finished", extra={"done": done, "failed": failed})
    return {"versions": len(rows), "done": done, "failed": failed}
