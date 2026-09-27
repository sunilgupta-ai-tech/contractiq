"""Phase 23: recovery of interrupted jobs and Qdrant snapshot round trip,
against the real PostgreSQL, Redis and Qdrant. No model is called.

Recovered jobs are queued on a throwaway arq queue, so the running worker
never picks them up, and every sweep is limited to the test's organization.
"""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from arq.connections import ArqRedis
from arq.jobs import JobStatus as ArqJobStatus
from qdrant_client import AsyncQdrantClient, models
from redis.asyncio import ConnectionPool
from sqlalchemy import select, update

from app.core.config import Settings
from app.db.database import Database
from app.db.models import (
    ContractType,
    Document,
    DocumentStatus,
    DocumentVersion,
    FileType,
    JobStatus,
    JobType,
    Organization,
    OrganizationStatus,
    ProcessingJob,
    User,
)
from app.ops.snapshots import restore_snapshot, save_snapshot
from app.queue import PROCESS_DOCUMENT, organization_deletion_job_id
from app.services.job_recovery import INTERRUPTED_MESSAGE, arq_status, recover
from app.storage import create_storage
from tests.integration.conftest import register

pytestmark = pytest.mark.skipif(
    os.getenv("CONTRACTIQ_INTEGRATION") != "1", reason="set CONTRACTIQ_INTEGRATION=1"
)

LONG_AGO = datetime.now(UTC) - timedelta(hours=3)


@pytest.fixture
async def queue():
    name = f"test-recovery:{uuid.uuid4().hex}"
    q = ArqRedis(ConnectionPool.from_url(Settings().redis_url), default_queue_name=name)
    yield q
    async for key in q.scan_iter(match="arq:*recovery-*"):
        await q.delete(key)
    await q.delete(name)
    await q.aclose()
    await q.connection_pool.disconnect()


async def _org_of(email: str, db: Database) -> uuid.UUID:
    async with db.session_factory() as s:
        return await s.scalar(select(User.organization_id).where(User.email == email))


async def _job(
    db: Database, org_id: uuid.UUID, *, status: JobStatus, attempts: int, updated: datetime
) -> uuid.UUID:
    """A document with one version and its processing job, as a crashed
    worker would leave them."""
    async with db.session_factory() as s:
        doc_status = (
            DocumentStatus.QUEUED if status is JobStatus.PENDING else DocumentStatus.EMBEDDING
        )
        document = Document(
            organization_id=org_id,
            title="Recovery test",
            contract_type=ContractType.OTHER,
            file_type=FileType.PDF,
            status=doc_status,
        )
        s.add(document)
        await s.flush()
        version = DocumentVersion(
            organization_id=org_id,
            document_id=document.id,
            version_number=1,
            label="v1",
            original_filename="r.pdf",
            storage_key=f"tenants/{org_id}/documents/{document.id}/r.pdf",
            mime_type="application/pdf",
            size_bytes=10,
            sha256=uuid.uuid4().hex * 2,
            status=doc_status,
        )
        s.add(version)
        await s.flush()
        job = ProcessingJob(
            organization_id=org_id,
            job_type=JobType.DOCUMENT_PROCESSING,
            status=status,
            document_version_id=version.id,
            attempts=attempts,
        )
        s.add(job)
        await s.flush()
        job.queue_job_id = str(job.id)
        await s.commit()
        # Set last, so the ORM's onupdate doesn't reset it.
        await s.execute(
            update(ProcessingJob).where(ProcessingJob.id == job.id).values(updated_at=updated)
        )
        await s.commit()
        return job.id


async def _state(
    db: Database, job_id: uuid.UUID
) -> tuple[ProcessingJob, DocumentVersion, Document]:
    async with db.session_factory() as s:
        job = await s.get(ProcessingJob, job_id)
        version = await s.get(DocumentVersion, job.document_version_id)
        document = await s.get(Document, version.document_id)
        return job, version, document


async def test_interrupted_jobs_are_requeued_or_given_up_and_live_ones_left_alone(
    api, cleanup, queue
):
    settings = Settings()
    db = Database(settings)
    _, email = register(api, cleanup, "Recovery Co")
    org_id = await _org_of(email, db)

    crashed = await _job(db, org_id, status=JobStatus.RUNNING, attempts=1, updated=LONG_AGO)
    exhausted = await _job(db, org_id, status=JobStatus.RUNNING, attempts=5, updated=LONG_AGO)
    backlog = await _job(db, org_id, status=JobStatus.PENDING, attempts=0, updated=LONG_AGO)
    lost = await _job(db, org_id, status=JobStatus.PENDING, attempts=0, updated=LONG_AGO)
    running_now = await _job(
        db, org_id, status=JobStatus.RUNNING, attempts=1, updated=datetime.now(UTC)
    )
    # The backlog job is still waiting in the queue: not lost, just slow.
    await queue.enqueue_job(PROCESS_DOCUMENT, str(backlog), _job_id=str(backlog))

    dry = await recover(db.session_factory, queue, settings, dry_run=True, organization_id=org_id)
    assert sorted(dry.requeued) == sorted([str(crashed), str(lost)])
    assert (await _state(db, crashed))[0].status is JobStatus.RUNNING  # nothing changed

    report = await recover(db.session_factory, queue, settings, organization_id=org_id)
    assert sorted(report.requeued) == sorted([str(crashed), str(lost)])
    assert report.failed == [str(exhausted)]
    assert report.held_by_queue == 1

    for job_id in (crashed, lost):
        job, version, document = await _state(db, job_id)
        assert job.status is JobStatus.PENDING
        assert job.queue_job_id.startswith(f"{job_id}:recovery-")
        assert version.status is document.status is DocumentStatus.QUEUED
        # Queued under the fresh id, with the ProcessingJob id as argument.
        assert await arq_status(queue, job.queue_job_id) is ArqJobStatus.queued

    job, version, document = await _state(db, exhausted)
    assert job.status is JobStatus.FAILED and job.finished_at is not None
    assert version.status is document.status is DocumentStatus.FAILED
    assert version.error_message == INTERRUPTED_MESSAGE

    for job_id, status in ((backlog, JobStatus.PENDING), (running_now, JobStatus.RUNNING)):
        assert (await _state(db, job_id))[0].status is status

    # Requeued jobs restart their stale clock: the next sweep leaves them be.
    again = await recover(db.session_factory, queue, settings, organization_id=org_id)
    assert not again.changed
    await db.dispose()


async def test_an_organization_deletion_lost_from_the_queue_is_queued_again(api, cleanup, queue):
    settings = Settings()
    db = Database(settings)
    _, email = register(api, cleanup, "Doomed Co")
    org_id = await _org_of(email, db)
    async with db.session_factory() as s:
        await s.execute(
            update(Organization)
            .where(Organization.id == org_id)
            .values(status=OrganizationStatus.DELETING, updated_at=LONG_AGO)
        )
        await s.commit()

    report = await recover(db.session_factory, queue, settings, organization_id=org_id)
    assert report.deletions_requeued == [str(org_id)]
    keys = [
        k
        async for k in queue.scan_iter(
            match=f"arq:job:{organization_deletion_job_id(str(org_id))}:recovery-*"
        )
    ]
    assert len(keys) == 1

    again = await recover(db.session_factory, queue, settings, organization_id=org_id)
    assert again.deletions_requeued == []
    await db.dispose()


async def test_qdrant_snapshot_is_saved_to_storage_and_restores_the_collection(tmp_path):
    collection = f"it_snapshot_{uuid.uuid4().hex[:10]}"
    settings = Settings(qdrant_collection=collection, local_storage_path=str(tmp_path))
    qdrant = AsyncQdrantClient(url=settings.qdrant_url)
    storage = create_storage(settings)
    await qdrant.create_collection(
        collection, vectors_config=models.VectorParams(size=4, distance=models.Distance.COSINE)
    )
    try:
        await qdrant.upsert(
            collection,
            points=[
                models.PointStruct(id=i, vector=[1.0, float(i), 0.0, 1.0], payload={"n": i})
                for i in range(1, 4)
            ],
            wait=True,
        )
        saved = await save_snapshot(qdrant, storage, settings, keep=1)
        assert saved.storage_key == f"backups/qdrant/{collection}/{saved.name}"
        assert saved.size_bytes > 0 and await storage.exists(saved.storage_key)

        # Lose the data, then bring it back from storage.
        await qdrant.delete(collection, points_selector=models.PointIdsList(points=[1, 2, 3]))
        assert (await qdrant.count(collection)).count == 0
        await restore_snapshot(storage, settings, saved.storage_key)
        assert (await qdrant.count(collection)).count == 3
    finally:
        for snapshot in await qdrant.list_snapshots(collection):
            await qdrant.delete_snapshot(collection, snapshot.name)
        await qdrant.delete_collection(collection)
        await qdrant.close()
