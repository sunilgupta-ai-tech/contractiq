"""Phase 21 end to end: large uploads are streamed (not held in memory),
limits apply to the stream, and flagged documents can be filtered and
marked reviewed."""

import hashlib
import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from app.core.config import Settings
from app.db.database import Database
from app.db.models import Document, DocumentVersion
from app.main import create_app
from app.storage import create_storage
from tests.integration.conftest import auth, register

pytestmark = pytest.mark.skipif(
    os.getenv("CONTRACTIQ_INTEGRATION") != "1", reason="set CONTRACTIQ_INTEGRATION=1"
)


def _big_pdf(mb: int) -> bytes:
    # A PDF header and a body the worker rejects quickly (no model calls).
    return b"%PDF-1.7\n% " + uuid.uuid4().hex.encode() + b"\n" + os.urandom(mb * 1024 * 1024)


async def test_a_large_upload_is_streamed_to_storage_intact(cleanup):
    with TestClient(create_app(Settings(max_upload_size_mb=40))) as api:
        tokens, _ = register(api, cleanup, "Big upload")
        data = _big_pdf(25)
        response = api.post(
            "/api/v1/documents/upload",
            headers=auth(tokens),
            files={"file": ("annual-report.pdf", data, "application/pdf")},
        )
        assert response.status_code == 202, response.text
        version = response.json()["data"]["version"]
        assert version["size_bytes"] == len(data)
        assert version["sha256"] == hashlib.sha256(data).hexdigest()

        db = Database(Settings())
        async with db.session_factory() as s:
            row = await s.get(DocumentVersion, uuid.UUID(version["id"]))
        await db.dispose()
        stored = await create_storage(Settings()).get(row.storage_key)
        assert hashlib.sha256(stored).hexdigest() == version["sha256"]

        too_big = api.post(
            "/api/v1/documents/upload",
            headers=auth(tokens),
            files={"file": ("huge.pdf", _big_pdf(41), "application/pdf")},
        )
        assert too_big.status_code == 413


async def test_flagged_documents_can_be_filtered_and_marked_reviewed(api, cleanup):
    tokens, _ = register(api, cleanup, "Review org")
    first = api.post(
        "/api/v1/documents/upload",
        headers=auth(tokens),
        files={"file": ("scan.pdf", _big_pdf(0), "application/pdf")},
    ).json()["data"]["document"]
    assert first["needs_review"] is False
    db = Database(Settings())
    async with db.session_factory() as s:
        await s.execute(
            update(Document).where(Document.id == uuid.UUID(first["id"])).values(needs_review=True)
        )
        await s.commit()
    await db.dispose()

    flagged = api.get("/api/v1/documents", params={"needs_review": "true"}, headers=auth(tokens))
    assert [d["id"] for d in flagged.json()["data"]["items"]] == [first["id"]]
    done = api.post(f"/api/v1/documents/{first['id']}/reviewed", headers=auth(tokens))
    assert done.status_code == 200 and done.json()["data"]["needs_review"] is False
    empty = api.get("/api/v1/documents", params={"needs_review": "true"}, headers=auth(tokens))
    assert empty.json()["data"]["items"] == []
