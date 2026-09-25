"""
`process_document` — the ingestion job.

State lives in PostgreSQL (ProcessingJob, DocumentVersion, Document), not
in Redis, so a worker crash or Redis restart never loses track of a
document. Each stage transition is committed immediately so the UI can
poll `/documents/{id}/status` and show live progress.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger, tenant_id_ctx
from app.db.models import Document, DocumentStatus, DocumentVersion, JobStatus, ProcessingJob

from ..services.pipeline import PIPELINE, Stage, StageContext

logger = get_logger("contractiq.worker.document_processing")


async def _set_status(
    session: AsyncSession,
    job: ProcessingJob,
    version: DocumentVersion,
    document: Document,
    doc_status: DocumentStatus,
    **job_fields: Any,
) -> None:
    """Update document + version status and job fields in one commit."""
    version.status = doc_status
    document.status = doc_status
    for key, value in job_fields.items():
        setattr(job, key, value)
    await session.commit()


async def process_document(ctx: dict[str, Any], job_id: str) -> dict[str, Any]:
    """Run every pipeline stage for the job's document version.

    Args:
        ctx: arq context; `ctx["resources"]` is created in worker startup.
        job_id: ProcessingJob primary key. Only the ID crosses the queue —
            never file contents or tenant data.

    Returns:
        Summary with final status and per-stage timings (stored in arq results).

    Raises:
        Re-raises stage exceptions after recording FAILED, so arq applies its
        retry policy; the DB row always reflects the final outcome.
    """
    resources = ctx["resources"]
    async with resources.db.session_factory() as session:
        job = await session.get(ProcessingJob, uuid.UUID(job_id))
        if job is None or job.document_version_id is None:
            logger.warning("job_not_found", extra={"job_id": job_id})
            return {"status": "missing"}
        version = await session.get(DocumentVersion, job.document_version_id)
        assert version is not None
        document = await session.get(Document, version.document_id)
        assert document is not None
        tenant_id_ctx.set(str(job.organization_id))

        stage_ctx = StageContext(
            tenant_id=str(job.organization_id),
            document_id=str(document.id),
            version_id=str(version.id),
            storage_key=version.storage_key,
            resources=resources,
        )
        timings: dict[str, float] = {}
        await _set_status(
            session,
            job,
            version,
            document,
            DocumentStatus.PROCESSING,
            status=JobStatus.RUNNING,
            started_at=datetime.now(UTC),
            attempts=job.attempts + 1,
            error_message=None,
        )

        stage: Stage | None = None
        try:
            for stage in PIPELINE:
                await _set_status(
                    session, job, version, document, stage.status, current_stage=stage.name
                )
                started = time.perf_counter()
                await stage.handler(stage_ctx)
                timings[stage.name] = round((time.perf_counter() - started) * 1000, 2)
                await _set_status(
                    session,
                    job,
                    version,
                    document,
                    stage.status,
                    progress=stage.progress,
                    stage_timings_ms=dict(timings),
                )
        except Exception as exc:
            logger.exception(
                "stage_failed", extra={"job_id": job_id, "stage": getattr(stage, "name", None)}
            )
            await session.rollback()
            version.error_message = "Processing failed. See job logs for details."
            await _set_status(
                session,
                job,
                version,
                document,
                DocumentStatus.FAILED,
                status=JobStatus.FAILED,
                error_message=f"{type(exc).__name__} in stage " f"{getattr(stage, 'name', '?')}",
                finished_at=datetime.now(UTC),
                stage_timings_ms=dict(timings),
            )
            raise

        await _set_status(
            session,
            job,
            version,
            document,
            DocumentStatus.COMPLETED,
            status=JobStatus.SUCCEEDED,
            current_stage=None,
            progress=100,
            finished_at=datetime.now(UTC),
        )
        document.current_version_id = version.id
        await session.commit()
        logger.info("document_processed", extra={"job_id": job_id, "timings_ms": timings})
        return {"status": "COMPLETED", "timings_ms": timings}
