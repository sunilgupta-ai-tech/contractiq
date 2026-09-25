"""
Worker integration test against real PostgreSQL, with the PDF stored in a
temporary local storage directory.

    make infra && make migrate
    cd workers && CONTRACTIQ_INTEGRATION=1 PYTHONPATH=../backend:.run pytest -q
"""

import json
import os
import uuid

import pytest
from qdrant_client.http import models as qm
from sqlalchemy import delete
from worker.services import pipeline
from worker.tasks.document_processing import process_document

from app.cache.redis import create_redis
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
from app.storage.local import LocalObjectStorage
from app.vectorstore.collections import ensure_collection
from app.vectorstore.qdrant import create_qdrant, tenant_filter
from tests import pdf_factory
from tests.fake_embeddings import FakeEmbeddings

pytestmark = pytest.mark.skipif(
    os.getenv("CONTRACTIQ_INTEGRATION") != "1", reason="set CONTRACTIQ_INTEGRATION=1"
)


class _Resources:
    """The subset of app Resources the pipeline uses.

    Real Postgres, Redis and Qdrant; a throwaway Qdrant collection; local
    storage in a temp dir; and the deterministic fake embedder instead of
    Gemini (no API key or network needed).
    """

    def __init__(self, db: Database, storage: LocalObjectStorage, collection: str) -> None:
        self.db = db
        self.storage = storage
        self.settings = Settings(qdrant_collection=collection, embedding_dimension=768)
        self.qdrant = create_qdrant(self.settings)
        self.redis = create_redis(self.settings)
        self.fake_embeddings = FakeEmbeddings(768)
        self.org_ids: list[uuid.UUID] = []  # created by _seed, deleted after the test

    def embeddings(self) -> FakeEmbeddings:
        return self.fake_embeddings


@pytest.fixture
async def env(tmp_path):
    db = Database(Settings())
    resources = _Resources(
        db, LocalObjectStorage(str(tmp_path)), f"test_chunks_{uuid.uuid4().hex[:10]}"
    )
    await ensure_collection(resources.qdrant, resources.settings.qdrant_collection, 768)
    yield db, resources
    # Deleting the organization cascades to its documents, versions and jobs,
    # so the test leaves no rows behind in the database.
    async with db.session_factory() as s:
        await s.execute(delete(Organization).where(Organization.id.in_(resources.org_ids)))
        await s.commit()
    # Embedding-cache entries are tenant-prefixed (ciq:<tenant>:emb:...).
    for org_id in resources.org_ids:
        async for key in resources.redis.scan_iter(match=f"ciq:{org_id}:*"):
            await resources.redis.delete(key)
    await resources.qdrant.delete_collection(resources.settings.qdrant_collection)
    await resources.qdrant.close()
    await resources.redis.aclose()
    await db.dispose()


async def _seed(resources: _Resources, pdf: bytes, *, newer_version_exists: bool = False) -> str:
    """Create org/document/version/job rows and store the PDF; returns the job ID.

    With `newer_version_exists`, a v2 row is also created (not processed), so
    the job processes an *older* version of the document.
    """
    db, storage = resources.db, resources.storage
    async with db.session_factory() as s:
        org = Organization(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}")
        s.add(org)
        await s.flush()
        resources.org_ids.append(org.id)
        doc = Document(title="Acme MSA", organization_id=org.id)
        s.add(doc)
        await s.flush()
        version_id = uuid.uuid4()
        key = f"tenants/{org.id}/documents/{doc.id}/{version_id}/original.pdf"
        await storage.put(key, pdf, "application/pdf")
        version = DocumentVersion(
            id=version_id,
            organization_id=org.id,
            document_id=doc.id,
            version_number=1,
            label="v1",
            original_filename="msa.pdf",
            storage_key=key,
            mime_type="application/pdf",
            size_bytes=len(pdf),
            sha256="0" * 64,
        )
        s.add(version)
        if newer_version_exists:
            s.add(
                DocumentVersion(
                    organization_id=org.id,
                    document_id=doc.id,
                    version_number=2,
                    label="v2",
                    original_filename="msa-v2.pdf",
                    storage_key=key.replace(str(version_id), "v2"),
                    mime_type="application/pdf",
                    size_bytes=1,
                    sha256="1" * 64,
                )
            )
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


async def test_pipeline_parses_pdf_and_records_results(env):
    db, resources = env
    job_id = await _seed(resources, pdf_factory.contract_pdf())
    result = await process_document({"resources": resources}, job_id)
    job, version, doc = await _load(db, job_id)

    assert result["status"] == "COMPLETED"
    assert job.status is JobStatus.SUCCEEDED and job.progress == 100
    assert set(job.stage_timings_ms) == {"parse", "ocr", "chunk", "embed", "index"}
    assert version.status is DocumentStatus.COMPLETED and doc.status is DocumentStatus.COMPLETED
    assert doc.current_version_id == version.id

    # Phase 4 results written to the version row...
    assert version.page_count == 3 and version.is_scanned is False
    meta = version.extraction_metadata
    assert meta["tables"] == 1 and meta["images"] == 1 and meta["warnings"] == []

    # ...and parsed.json + the image saved next to the original PDF.
    parsed = json.loads(await resources.storage.get(meta["parsed_key"]))
    assert [p["number"] for p in parsed["pages"]] == [1, 2, 3]
    image_key = parsed["pages"][2]["images"][0]["storage_key"]
    assert (await resources.storage.get(image_key)).startswith(b"\x89PNG")

    # Phase 5: chunks.json saved, child count recorded on the version.
    chunks = json.loads(await resources.storage.get(meta["chunks_key"]))
    children = [c for c in chunks["chunks"] if c["level"] == "child"]
    assert version.chunk_count == len(children) > 0
    assert meta["parent_chunks"] >= 1 and meta["chunker_version"] == chunks["chunker_version"]
    # The user's document title roots every heading path.
    assert all(c["heading_path"][0] == "Acme MSA" for c in children)

    # Phase 6: every chunk is a Qdrant point in this tenant, marked current.
    collection = resources.settings.qdrant_collection
    tenant = tenant_filter(str(doc.organization_id), version_ids=[str(version.id)])
    points = (await resources.qdrant.count(collection, count_filter=tenant, exact=True)).count
    assert points == meta["indexed_points"] > version.chunk_count  # children + parents
    assert meta["embedding_model"] == "fake:hash-embed:768"
    assert meta["embedding"]["texts"] == version.chunk_count
    current = qm.Filter(
        must=[*tenant.must, qm.FieldCondition(key="is_current", match=qm.MatchValue(value=True))]
    )
    assert (await resources.qdrant.count(collection, count_filter=current)).count == points


async def test_reprocessing_an_older_version_does_not_make_it_current(env):
    db, resources = env
    job_id = await _seed(resources, pdf_factory.contract_pdf(), newer_version_exists=True)
    await process_document({"resources": resources}, job_id)
    job, version, doc = await _load(db, job_id)
    assert version.status is DocumentStatus.COMPLETED
    assert doc.current_version_id != version.id
    stale = qm.Filter(
        must=[
            *tenant_filter(str(doc.organization_id), version_ids=[str(version.id)]).must,
            qm.FieldCondition(key="is_current", match=qm.MatchValue(value=True)),
        ]
    )
    collection = resources.settings.qdrant_collection
    assert (await resources.qdrant.count(collection, count_filter=stale)).count == 0


async def test_embedding_cache_makes_reprocessing_free(env):
    db, resources = env
    first = await _seed(resources, pdf_factory.contract_pdf())
    await process_document({"resources": resources}, first)
    calls_after_first = len(resources.fake_embeddings.calls)
    # Same tenant, same text again (e.g. a retried job): served from Redis.
    await process_document({"resources": resources}, first)
    assert len(resources.fake_embeddings.calls) == calls_after_first
    _, version, _ = await _load(db, first)
    stats = version.extraction_metadata["embedding"]
    assert stats["cache_hits"] == stats["texts"] and stats["api_calls"] == 0


async def test_password_protected_pdf_fails_permanently_without_retry(env):
    db, resources = env
    job_id = await _seed(resources, pdf_factory.encrypted_pdf())
    # Returns instead of raising: arq must not retry a file that can never open.
    result = await process_document({"resources": resources}, job_id)
    job, version, doc = await _load(db, job_id)

    assert result["status"] == "FAILED"
    assert job.status is JobStatus.FAILED and doc.status is DocumentStatus.FAILED
    assert version.error_message == "The PDF is password-protected. Upload an unlocked copy."
    assert job.error_message == "EncryptedPdfError in stage parse"


async def test_transient_stage_failure_marks_job_failed_and_reraises(env, monkeypatch):
    async def boom(ctx):
        raise RuntimeError("storage timeout")

    failing = tuple(
        pipeline.Stage(s.name, s.status, boom if s.name == "chunk" else s.handler, s.progress)
        for s in pipeline.PIPELINE
    )
    monkeypatch.setattr("worker.tasks.document_processing.PIPELINE", failing)
    db, resources = env
    job_id = await _seed(resources, pdf_factory.contract_pdf())
    with pytest.raises(RuntimeError):  # re-raised so arq retries it
        await process_document({"resources": resources}, job_id)
    job, version, doc = await _load(db, job_id)
    assert job.status is JobStatus.FAILED
    assert job.error_message == "RuntimeError in stage chunk"
    assert version.error_message == "Processing failed. See job logs for details."
    assert doc.status is DocumentStatus.FAILED
    assert set(job.stage_timings_ms) == {"parse", "ocr"}
    assert version.page_count == 3  # results of completed stages are kept
