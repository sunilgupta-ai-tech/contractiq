"""Phase 19: duplicate documents are detected by content, per organization,
and never leak across organizations."""

import hashlib
import os
import uuid

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.db.database import Database
from app.db.models import (
    Document,
    DocumentStatus,
    DocumentVersion,
    Organization,
    ProcessingJob,
    User,
)
from tests.integration.conftest import auth, register

pytestmark = pytest.mark.skipif(
    os.getenv("CONTRACTIQ_INTEGRATION") != "1", reason="set CONTRACTIQ_INTEGRATION=1"
)

DUPLICATE_MESSAGE = "This document already exists in your organization."


def _pdf() -> bytes:
    # Not a real PDF body: the worker fails it quickly, so no model is called.
    return f"%PDF-1.7\n% {uuid.uuid4()}\ntrailer<<>>\n%%EOF\n".encode()


def _upload(api, tokens, data: bytes, filename: str = "contract.pdf", **form):
    return api.post(
        "/api/v1/documents/upload",
        headers=auth(tokens),
        files={"file": (filename, data, "application/pdf")},
        data={k: str(v) for k, v in form.items()},
    )


async def _org_of(email: str) -> uuid.UUID:
    db = Database(Settings())
    async with db.session_factory() as s:
        org_id = await s.scalar(select(User.organization_id).where(User.email == email))
    await db.dispose()
    return org_id


async def _counts(org_id: uuid.UUID) -> tuple[int, int]:
    """(versions, processing jobs) stored for the organization."""
    db = Database(Settings())
    async with db.session_factory() as s:
        versions = await s.scalar(
            select(func.count())
            .select_from(DocumentVersion)
            .where(DocumentVersion.organization_id == org_id)
        )
        jobs = await s.scalar(
            select(func.count())
            .select_from(ProcessingJob)
            .where(ProcessingJob.organization_id == org_id)
        )
    await db.dispose()
    return int(versions), int(jobs)


async def test_same_file_in_same_organization_is_not_stored_or_processed_again(api, cleanup):
    tokens, email = register(api, cleanup, "Dup same")
    org_id = await _org_of(email)
    data = _pdf()
    first = _upload(api, tokens, data, "MSA.pdf")
    assert first.status_code == 202, first.text
    before = await _counts(org_id)

    # Same bytes under another name, as a new document or as a new version.
    for attempt in (
        _upload(api, tokens, data, "MSA copy.pdf"),
        _upload(api, tokens, data, "v2.pdf", document_id=first.json()["data"]["document"]["id"]),
    ):
        assert attempt.status_code == 409
        error = attempt.json()["error"]
        assert error["code"] == "DUPLICATE_DOCUMENT"
        assert error["message"] == DUPLICATE_MESSAGE
        assert error["details"]["document_id"] == first.json()["data"]["document"]["id"]
        assert error["details"]["document_title"] == "MSA"
    # Nothing new was stored or queued for processing (no second embedding).
    assert await _counts(org_id) == before


async def test_same_name_with_different_content_is_a_new_document(api, cleanup):
    tokens, _ = register(api, cleanup, "Dup name")
    first = _upload(api, tokens, _pdf(), "policy.pdf")
    second = _upload(api, tokens, _pdf(), "policy.pdf")
    assert first.status_code == second.status_code == 202
    assert first.json()["data"]["document"]["id"] != second.json()["data"]["document"]["id"]


async def test_organizations_never_see_each_others_copies(api, cleanup):
    tokens_a, _ = register(api, cleanup, "Dup A")
    tokens_b, _ = register(api, cleanup, "Dup B")
    data = _pdf()
    in_a = _upload(api, tokens_a, data)
    in_b = _upload(api, tokens_b, data)
    # Both accepted independently; B's response says nothing about A.
    assert in_a.status_code == in_b.status_code == 202
    doc_a = in_a.json()["data"]["document"]["id"]
    assert doc_a not in in_b.text
    assert api.get(f"/api/v1/documents/{doc_a}", headers=auth(tokens_b)).status_code == 404
    # Each organization still detects its own duplicate.
    assert _upload(api, tokens_b, data).json()["error"]["code"] == "DUPLICATE_DOCUMENT"


async def test_a_failed_upload_can_be_uploaded_again(api, cleanup):
    tokens, _ = register(api, cleanup, "Dup failed")
    data = _pdf()
    first = _upload(api, tokens, data).json()["data"]
    db = Database(Settings())
    async with db.session_factory() as s:
        await s.execute(
            update(DocumentVersion)
            .where(DocumentVersion.id == uuid.UUID(first["version"]["id"]))
            .values(status=DocumentStatus.FAILED)
        )
        await s.commit()
    await db.dispose()
    assert _upload(api, tokens, data).status_code == 202


async def test_a_duplicate_is_reported_as_such_not_as_a_plan_limit(api, cleanup):
    tokens, email = register(api, cleanup, "Dup limit")
    data = _pdf()
    assert _upload(api, tokens, data).status_code == 202
    db = Database(Settings())
    async with db.session_factory() as s:
        await s.execute(
            update(Organization)
            .where(Organization.id == await _org_of(email))
            .values(max_documents=1)
        )
        await s.commit()
    await db.dispose()
    assert _upload(api, tokens, data).json()["error"]["code"] == "DUPLICATE_DOCUMENT"
    assert _upload(api, tokens, _pdf()).json()["error"]["code"] == "PLAN_LIMIT_REACHED"


async def test_the_database_allows_one_live_copy_per_organization(api, cleanup):
    """What makes simultaneous uploads safe: the unique index is per
    organization and ignores failed versions."""
    _, email_a = register(api, cleanup, "Dup index A")
    _, email_b = register(api, cleanup, "Dup index B")
    org_a, org_b = await _org_of(email_a), await _org_of(email_b)
    sha = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
    db = Database(Settings())

    async def add(org_id: uuid.UUID, status: DocumentStatus = DocumentStatus.QUEUED) -> None:
        async with db.session_factory() as s:
            doc = Document(organization_id=org_id, title="x", tags=[])
            s.add(doc)
            await s.flush()
            s.add(
                DocumentVersion(
                    organization_id=org_id,
                    document_id=doc.id,
                    version_number=1,
                    label="v1",
                    original_filename="x.pdf",
                    storage_key=f"tenants/{org_id}/documents/{doc.id}/x",
                    mime_type="application/pdf",
                    size_bytes=1,
                    sha256=sha,
                    status=status,
                )
            )
            await s.commit()

    try:
        await add(org_a)
        await add(org_b)  # another organization: independent
        await add(org_a, DocumentStatus.FAILED)  # failed copies don't count
        with pytest.raises(IntegrityError):
            await add(org_a)
    finally:
        await db.dispose()
