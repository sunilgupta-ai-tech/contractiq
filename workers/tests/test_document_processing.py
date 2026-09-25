"""
Worker integration test against real PostgreSQL.

    make infra && make migrate
    cd workers && CONTRACTIQ_INTEGRATION=1 PYTHONPATH=../backend:.run pytest -q
"""

import os
import uuid

import pytest
from worker.services import pipeline
from worker.tasks.document_processing import process_document

from app.core.config import Settings
from app.db.database import Database
from app.db.models import (
    Document,
    DocumentStatus,
    DocumentVersion,
    JobStatus,
    JobType,
    Organization,
    ProcessingJob,
)

pytestmark = pytest.mark.skipif(
    os.getenv("CONTRACTIQ_INTEGRATION") != "1", reason="set CONTRACTIQ_INTEGRATION=1"
)


class _Resources:
    def __init__(self, db: Database) -> None:
        self.db = db


async def _seed(db: Database) -> str:
    async with db.session_factory() as s:
        org = Organization(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}")
        s.add(org)
        await s.flush()
        doc = Document(title="Acme MSA", organization_id=org.id)
        s.add(doc)
        await s.flush()
        version = DocumentVersion(
            organization_id=org.id,
            document_id=doc.id,
            version_number=1,
            label="v1",
            original_filename="msa.pdf",
            storage_key="k",
            mime_type="application/pdf",
            size_bytes=10,
            sha256="0" * 64,
        )
        s.add(version)
        await s.flush()
        job = ProcessingJob(
            organization_id=org.id,
            job_type=JobType.DOCUMENT_PROCESSING,
            document_version_id=version.id,
        )
        s.add(job)
        await s.commit()
        return str(job.id)


async def _load(db: Database, job_id: str):
    async with db.session_factory() as s:
        job = await s.get(ProcessingJob, uuid.UUID(job_id))
        version = await s.get(DocumentVersion, job.document_version_id)
        doc = await s.get(Document, version.document_id)
        return job, version, doc


async def test_pipeline_completes_and_records_stage_timings():
    db = Database(Settings())
    job_id = await _seed(db)
    result = await process_document({"resources": _Resources(db)}, job_id)
    job, version, doc = await _load(db, job_id)
    assert result["status"] == "COMPLETED"
    assert job.status is JobStatus.SUCCEEDED and job.progress == 100
    assert set(job.stage_timings_ms) == {"parse", "ocr", "chunk", "embed", "index"}
    assert version.status is DocumentStatus.COMPLETED and doc.status is DocumentStatus.COMPLETED
    assert doc.current_version_id == version.id
    await db.dispose()


async def test_stage_failure_marks_job_failed(monkeypatch):
    async def boom(ctx):
        raise RuntimeError("corrupt xref table")

    failing = tuple(
        pipeline.Stage(s.name, s.status, boom if s.name == "chunk" else s.handler, s.progress)
        for s in pipeline.PIPELINE
    )
    monkeypatch.setattr("worker.tasks.document_processing.PIPELINE", failing)
    db = Database(Settings())
    job_id = await _seed(db)
    with pytest.raises(RuntimeError):
        await process_document({"resources": _Resources(db)}, job_id)
    job, version, doc = await _load(db, job_id)
    assert job.status is JobStatus.FAILED
    assert job.error_message == "RuntimeError in stage chunk"
    assert doc.status is DocumentStatus.FAILED
    assert set(job.stage_timings_ms) == {"parse", "ocr"}
    await db.dispose()
