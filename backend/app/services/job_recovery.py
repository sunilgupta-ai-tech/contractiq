"""
Recovery of interrupted background work (Phase 23).

PostgreSQL is the source of truth for background work and Redis (arq) is
only transport (see app/queue.py). That lets a periodic sweep repair what a
worker crash or a Redis loss leaves behind:

* A document job that has been PENDING or RUNNING for too long, and that arq
  no longer holds (not queued, deferred or in progress), was lost: the
  worker died mid-job and arq gave up, or Redis lost the queue. It is queued
  again, up to JOB_RECOVERY_MAX_ATTEMPTS starts, and then marked FAILED with
  a message telling the user to upload the file again.
* An organization that has been DELETING for too long is queued for
  deletion again. Erasure is idempotent, so a second run is harmless.

Jobs arq still holds are never touched, so a long backlog or a slow OCR run
is not mistaken for a lost job. A requeued job gets a fresh arq id, because
arq keeps the interrupted run's result under the old id for a day and would
ignore a new enqueue under it.

The worker runs the sweep every JOB_RECOVERY_INTERVAL_MIN minutes. It is an
arq cron job, so only one worker runs it at a time. It also runs on demand
with `python -m app.ops recover`, e.g. right after Redis was restored.
Candidate rows are locked with SKIP LOCKED, so two sweeps never handle the
same job.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from arq.connections import ArqRedis
from arq.jobs import Job
from arq.jobs import JobStatus as ArqJobStatus
from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.logging import get_logger
from app.db.models import (
    Document,
    DocumentStatus,
    DocumentVersion,
    JobStatus,
    JobType,
    Organization,
    OrganizationStatus,
    ProcessingJob,
)
from app.observability import metrics
from app.queue import (
    enqueue_document_processing,
    enqueue_organization_deletion,
    organization_deletion_job_id,
)

logger = get_logger("contractiq.recovery")

INTERRUPTED_MESSAGE = (
    "Processing was interrupted repeatedly and has stopped. Please upload the document again."
)
# arq still owns these: the job will run (or is running), so leave it alone.
_HELD = frozenset({ArqJobStatus.queued, ArqJobStatus.deferred, ArqJobStatus.in_progress})


class Action(StrEnum):
    LEAVE = "leave"
    REQUEUE = "requeue"
    FAIL = "fail"


def decide(arq_status: ArqJobStatus, attempts: int, max_attempts: int) -> Action:
    """What to do with a job that has been idle past its stale limit."""
    if arq_status in _HELD:
        return Action.LEAVE
    if attempts >= max_attempts:
        return Action.FAIL
    return Action.REQUEUE


@dataclass
class RecoveryReport:
    requeued: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    deletions_requeued: list[str] = field(default_factory=list)
    held_by_queue: int = 0  # stale in PostgreSQL, but arq still has them
    dry_run: bool = False

    @property
    def changed(self) -> bool:
        return bool(self.requeued or self.failed or self.deletions_requeued)

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def stale_jobs_filter(settings: Settings) -> ColumnElement[bool]:
    """PENDING or RUNNING document jobs idle past their limits. The database
    clock is used for both sides, so app/database clock skew doesn't matter."""
    now = func.now()
    return and_(
        ProcessingJob.job_type == JobType.DOCUMENT_PROCESSING,
        or_(
            and_(
                ProcessingJob.status == JobStatus.PENDING,
                ProcessingJob.updated_at < now - timedelta(seconds=settings.job_stale_pending_s),
            ),
            and_(
                ProcessingJob.status == JobStatus.RUNNING,
                ProcessingJob.updated_at < now - timedelta(seconds=settings.job_stale_running_s),
            ),
        ),
    )


async def arq_status(queue: ArqRedis, arq_job_id: str) -> ArqJobStatus:
    return await Job(arq_job_id, queue, _queue_name=queue.default_queue_name).status()


async def recover(
    session_factory: async_sessionmaker[AsyncSession],
    queue: ArqRedis,
    settings: Settings,
    *,
    dry_run: bool = False,
    organization_id: uuid.UUID | None = None,
    limit: int = 500,
) -> RecoveryReport:
    """One sweep. Runs without a tenant binding (like the worker's job
    lookup), because lost jobs can belong to any organization;
    `organization_id` limits it to one."""
    report = RecoveryReport(dry_run=dry_run)
    await _recover_document_jobs(session_factory, queue, settings, report, organization_id, limit)
    await _recover_deletions(session_factory, queue, settings, report, organization_id)
    if report.changed or report.held_by_queue:
        logger.info("recovery_sweep", extra=report.as_dict())
    return report


async def _recover_document_jobs(
    session_factory: async_sessionmaker[AsyncSession],
    queue: ArqRedis,
    settings: Settings,
    report: RecoveryReport,
    organization_id: uuid.UUID | None,
    limit: int,
) -> None:
    query = select(ProcessingJob)
    if organization_id is not None:
        query = query.where(ProcessingJob.organization_id == organization_id)
    to_enqueue: list[tuple[str, str]] = []
    async with session_factory() as session:
        jobs = (
            await session.scalars(
                query.join(Organization, Organization.id == ProcessingJob.organization_id)
                # A deleting organization's jobs are about to be erased with it.
                .where(
                    stale_jobs_filter(settings), Organization.status != OrganizationStatus.DELETING
                )
                .order_by(ProcessingJob.updated_at)
                .limit(limit)
                .with_for_update(of=ProcessingJob, skip_locked=True)
            )
        ).all()
        for job in jobs:
            current_id = job.queue_job_id or str(job.id)
            status = await arq_status(queue, current_id)
            action = decide(status, job.attempts, settings.job_recovery_max_attempts)
            if action is Action.LEAVE:
                report.held_by_queue += 1
                continue
            version = (
                await session.get(DocumentVersion, job.document_version_id)
                if job.document_version_id
                else None
            )
            document = await session.get(Document, version.document_id) if version else None
            if document is None:
                action = Action.FAIL  # nothing left to process
            (report.requeued if action is Action.REQUEUE else report.failed).append(str(job.id))
            if report.dry_run:
                continue
            if action is Action.REQUEUE and version is not None and document is not None:
                new_id = f"{job.id}:recovery-{uuid.uuid4().hex[:8]}"
                job.status, job.queue_job_id = JobStatus.PENDING, new_id
                job.error_message = f"Requeued after an interruption (queue: {status.value})."
                job.updated_at = func.now()  # restarts the stale clock
                version.status = document.status = DocumentStatus.QUEUED
                to_enqueue.append((str(job.id), new_id))
            else:
                job.status, job.finished_at = JobStatus.FAILED, datetime.now(UTC)
                job.error_message = f"Given up by recovery after {job.attempts} start(s)."
                if version is not None:
                    version.status = DocumentStatus.FAILED
                    version.error_message = INTERRUPTED_MESSAGE
                if document is not None:
                    document.status = DocumentStatus.FAILED
            metrics.JOBS_RECOVERED.labels(kind="document", action=action.value).inc()
        await session.commit()

    # After the commit, so the worker never picks up a job whose row still
    # says RUNNING. If Redis refuses, the rows stay PENDING and the next
    # sweep tries again.
    for job_id, new_id in to_enqueue:
        try:
            await enqueue_document_processing(queue, job_id, arq_job_id=new_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("recovery_enqueue_failed", extra={"job_id": job_id, "error": repr(exc)})


async def _recover_deletions(
    session_factory: async_sessionmaker[AsyncSession],
    queue: ArqRedis,
    settings: Settings,
    report: RecoveryReport,
    organization_id: uuid.UUID | None,
) -> None:
    query = select(Organization)
    if organization_id is not None:
        query = query.where(Organization.id == organization_id)
    to_enqueue: list[tuple[str, str]] = []
    async with session_factory() as session:
        orgs = (
            await session.scalars(
                query.where(
                    Organization.status == OrganizationStatus.DELETING,
                    Organization.updated_at
                    < func.now() - timedelta(seconds=settings.job_stale_running_s),
                ).with_for_update(skip_locked=True)
            )
        ).all()
        for org in orgs:
            if await arq_status(queue, organization_deletion_job_id(str(org.id))) in _HELD:
                report.held_by_queue += 1
                continue
            report.deletions_requeued.append(str(org.id))
            if report.dry_run:
                continue
            # Touching the row restarts the stale clock, so a requeued
            # deletion isn't queued again on every sweep while it runs.
            org.updated_at = func.now()
            base_id = organization_deletion_job_id(str(org.id))
            to_enqueue.append((str(org.id), f"{base_id}:recovery-{uuid.uuid4().hex[:8]}"))
            metrics.JOBS_RECOVERED.labels(kind="organization_deletion", action="requeue").inc()
        await session.commit()

    for org_id, new_id in to_enqueue:
        try:
            await enqueue_organization_deletion(queue, org_id, arq_job_id=new_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "recovery_enqueue_failed", extra={"organization_id": org_id, "error": repr(exc)}
            )
