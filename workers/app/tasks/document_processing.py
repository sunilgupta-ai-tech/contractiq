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

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger, tenant_id_ctx
from app.db.models import Document, DocumentStatus, DocumentVersion, JobStatus, ProcessingJob
from app.document_processing.parser import PdfProcessingError

from ..services.pipeline import PIPELINE, Stage, StageContext

logger = get_logger("contractiq.worker.document_processing")

GENERIC_FAILURE = "Processing failed. See job logs for details."


def _apply_version_updates(version: DocumentVersion, updates: dict[str, Any]) -> None:
    """Write fields collected by stages (page_count, is_scanned,
    extraction_metadata) onto the version row. Applied on success *and*
    failure, so e.g. the page count is known even if a later stage failed."""
    for column, value in updates.items():
        setattr(version, column, value)


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
        Re-raises *transient* stage exceptions after recording FAILED, so arq
        applies its retry policy; the DB row always reflects the final outcome.
        A PdfProcessingError (encrypted/corrupt/oversized file) is permanent:
        it is recorded with its user-facing message and NOT re-raised, because
        retrying the same bytes can never succeed.
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

        # Is this the document's newest version? Only the newest becomes the
        # "current" one (searched by default); re-processing an older version
        # must not demote a newer one.
        newest = await session.scalar(
            select(func.max(DocumentVersion.version_number)).where(
                DocumentVersion.document_id == document.id
            )
        )
        is_latest = version.version_number >= (newest or 0)

        stage_ctx = StageContext(
            tenant_id=str(job.organization_id),
            document_id=str(document.id),
            version_id=str(version.id),
            storage_key=version.storage_key,
            resources=resources,
            document_title=document.title,
            version_label=version.label,
            contract_type=document.contract_type.value,
            is_latest_version=is_latest,
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
            permanent = isinstance(exc, PdfProcessingError)
            stage_name = getattr(stage, "name", None)
            if permanent:
                # Expected outcome for a bad file: no stack trace needed.
                logger.warning(
                    "document_rejected",
                    extra={"job_id": job_id, "stage": stage_name, "reason": type(exc).__name__},
                )
            else:
                logger.exception("stage_failed", extra={"job_id": job_id, "stage": stage_name})
            await session.rollback()
            _apply_version_updates(version, stage_ctx.version_updates)
            # Only PdfProcessingError messages are written for users; other
            # exception text may contain internals and stays in the logs.
            version.error_message = (
                exc.user_message if isinstance(exc, PdfProcessingError) else GENERIC_FAILURE
            )
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
            if isinstance(exc, PdfProcessingError):
                return {"status": "FAILED", "reason": exc.user_message, "timings_ms": timings}
            raise

        _apply_version_updates(version, stage_ctx.version_updates)
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
        if is_latest:
            document.current_version_id = version.id
        await session.commit()
        logger.info("document_processed", extra={"job_id": job_id, "timings_ms": timings})
        return {"status": "COMPLETED", "timings_ms": timings}
