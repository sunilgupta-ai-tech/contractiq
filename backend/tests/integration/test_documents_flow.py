"""
End-to-end document upload, versioning, status, tenant isolation and delete
against real PostgreSQL, Redis, Qdrant and local storage.

Run with the stack up (`make infra && make migrate`):
    CONTRACTIQ_INTEGRATION=1 pytest tests/integration
"""

import os
import uuid

import pytest
from redis.asyncio import Redis
from sqlalchemy import select

from app.core.config import Settings
from app.db.database import Database
from app.db.models import AuditLog, DocumentVersion
from app.storage import create_storage
from tests.integration.conftest import PASSWORD, auth, new_email, register

pytestmark = pytest.mark.skipif(
    os.getenv("CONTRACTIQ_INTEGRATION") != "1", reason="set CONTRACTIQ_INTEGRATION=1"
)


def _pdf() -> bytes:
    """A distinct PDF each call, so uploads don't collide on the hash."""
    return f"%PDF-1.7\n% {uuid.uuid4()}\ntrailer<<>>\n%%EOF\n".encode()


def _upload(api, tokens, data=None, filename="Master_Services_Agreement.pdf", **form):
    return api.post(
        "/api/v1/documents/upload",
        headers=auth(tokens),
        files={"file": (filename, data or _pdf(), "application/pdf")},
        data={k: str(v) for k, v in form.items()},
    )


async def _version_row(version_id: str) -> DocumentVersion:
    db = Database(Settings())
    async with db.session_factory() as session:
        row = await session.get(DocumentVersion, uuid.UUID(version_id))
    await db.dispose()
    assert row is not None
    return row


async def test_upload_stores_file_creates_rows_and_enqueues(api, cleanup):
    admin, _ = register(api, cleanup, "Docs Alpha")
    response = _upload(api, admin, contract_type="MSA", counterparty="Northwind")
    assert response.status_code == 202, response.text
    result = response.json()["data"]

    doc, version, job = result["document"], result["version"], result["job"]
    assert doc["title"] == "Master Services Agreement"
    assert doc["contract_type"] == "MSA" and doc["counterparty"] == "Northwind"
    assert doc["status"] == "QUEUED" and doc["version_count"] == 1
    assert version["label"] == "v1" and version["status"] == "QUEUED"
    assert job["status"] == "PENDING" and job["document_version_id"] == version["id"]
    assert "storage_key" not in version  # internal paths are never exposed

    row = await _version_row(version["id"])
    assert row.storage_key.endswith("/original.pdf")
    assert f"tenants/{row.organization_id}/" in row.storage_key
    assert await create_storage(Settings()).exists(row.storage_key)

    # Enqueued under the job's own ID. A running worker may already have
    # picked it up, so accept any arq state for it.
    redis = Redis.from_url(Settings().redis_url)
    keys = [f"arq:{kind}:{job['id']}" for kind in ("job", "in-progress", "result")]
    assert await redis.exists(*keys) >= 1
    await redis.aclose()


def test_duplicate_upload_is_rejected_with_a_pointer(api, cleanup):
    admin, _ = register(api, cleanup, "Docs Beta")
    data = _pdf()
    first = _upload(api, admin, data=data).json()["data"]
    again = _upload(api, admin, data=data, filename="copy.pdf")
    assert again.status_code == 409
    assert again.json()["error"]["details"]["document_id"] == first["document"]["id"]

    # The same bytes in a different organization are not a duplicate.
    other, _ = register(api, cleanup, "Docs Beta Two")
    assert _upload(api, other, data=data).status_code == 202


def test_new_version_of_existing_document(api, cleanup):
    admin, _ = register(api, cleanup, "Docs Gamma")
    doc_id = _upload(api, admin).json()["data"]["document"]["id"]

    v2 = _upload(api, admin, filename="MSA-amended.pdf", document_id=doc_id)
    assert v2.status_code == 202, v2.text
    assert v2.json()["data"]["version"]["version_number"] == 2
    assert v2.json()["data"]["version"]["label"] == "v2"

    v3 = _upload(api, admin, document_id=doc_id, version_label="Amendment 2")
    assert v3.json()["data"]["version"]["label"] == "Amendment 2"

    detail = api.get(f"/api/v1/documents/{doc_id}", headers=auth(admin)).json()["data"]
    assert [v["version_number"] for v in detail["versions"]] == [1, 2, 3]
    assert detail["latest_version"]["version_number"] == 3


def test_invalid_file_creates_nothing(api, cleanup):
    admin, _ = register(api, cleanup, "Docs Delta")
    bad = _upload(api, admin, data=b"MZ\x90\x00 definitely not a pdf", filename="x.pdf")
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "INVALID_FILE"
    listing = api.get("/api/v1/documents", headers=auth(admin)).json()["data"]
    assert listing["total"] == 0


def test_list_search_filters_status_and_job(api, cleanup):
    admin, _ = register(api, cleanup, "Docs Epsilon")
    nda = _upload(api, admin, title="Mutual NDA", contract_type="NDA").json()["data"]
    _upload(api, admin, title="Cloud Hosting SLA", contract_type="SLA", counterparty="Stratus")

    def titles(**params):
        page = api.get("/api/v1/documents", headers=auth(admin), params=params).json()["data"]
        return {d["title"] for d in page["items"]}

    assert titles() == {"Mutual NDA", "Cloud Hosting SLA"}
    assert titles(q="stratus") == {"Cloud Hosting SLA"}  # counterparty, case-insensitive
    assert titles(contract_type="NDA") == {"Mutual NDA"}
    assert titles(q="100%_") == set()  # LIKE wildcards are escaped

    doc_id = nda["document"]["id"]
    status = api.get(f"/api/v1/documents/{doc_id}/status", headers=auth(admin)).json()["data"]
    assert status["version_id"] == nda["version"]["id"]
    assert status["job"]["id"] == nda["job"]["id"]

    job = api.get(f"/api/v1/jobs/{nda['job']['id']}", headers=auth(admin))
    assert job.status_code == 200 and job.json()["data"]["job_type"] == "DOCUMENT_PROCESSING"


def test_documents_are_invisible_across_tenants(api, cleanup):
    admin_a, _ = register(api, cleanup, "Docs Tenant A")
    admin_b, _ = register(api, cleanup, "Docs Tenant B")
    a = _upload(api, admin_a).json()["data"]
    doc_id, job_id = a["document"]["id"], a["job"]["id"]

    for path in (
        f"/api/v1/documents/{doc_id}",
        f"/api/v1/documents/{doc_id}/status",
        f"/api/v1/jobs/{job_id}",
    ):
        assert api.get(path, headers=auth(admin_b)).status_code == 404, path
    assert api.delete(f"/api/v1/documents/{doc_id}", headers=auth(admin_b)).status_code == 404
    assert _upload(api, admin_b, document_id=doc_id).status_code == 404
    assert api.get("/api/v1/documents", headers=auth(admin_b)).json()["data"]["total"] == 0


def test_viewers_read_but_cannot_upload(api, cleanup):
    admin, _ = register(api, cleanup, "Docs Zeta")
    doc_id = _upload(api, admin).json()["data"]["document"]["id"]
    email = new_email("viewer")
    api.post(
        "/api/v1/users",
        headers=auth(admin),
        json={"email": email, "full_name": "V", "password": PASSWORD, "role": "VIEWER"},
    )
    viewer = api.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()[
        "data"
    ]
    assert api.get(f"/api/v1/documents/{doc_id}", headers=auth(viewer)).status_code == 200
    assert _upload(api, viewer).status_code == 403


async def test_delete_removes_rows_files_and_is_audited(api, cleanup):
    admin, _ = register(api, cleanup, "Docs Eta")
    result = _upload(api, admin).json()["data"]
    doc_id, job_id = result["document"]["id"], result["job"]["id"]
    key = (await _version_row(result["version"]["id"])).storage_key
    # A file the worker derives next to the PDF (Phase 4) must go too.
    storage = create_storage(Settings())
    derived = key.replace("original.pdf", "parsed.json")
    await storage.put(derived, b"{}", "application/json")

    response = api.delete(f"/api/v1/documents/{doc_id}", headers=auth(admin))
    assert response.status_code == 204
    assert api.get(f"/api/v1/documents/{doc_id}", headers=auth(admin)).status_code == 404
    assert api.get(f"/api/v1/jobs/{job_id}", headers=auth(admin)).status_code == 404
    assert not await storage.exists(key)
    assert not await storage.exists(derived)

    db = Database(Settings())
    async with db.session_factory() as session:
        actions = (
            await session.execute(select(AuditLog.action).where(AuditLog.resource_id == doc_id))
        ).scalars()
        assert set(actions) == {"document.upload", "document.delete"}
    await db.dispose()
