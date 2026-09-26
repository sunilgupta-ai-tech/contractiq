"""Phase 15: the Documents library — file-type tabs, search by title or
file name, sorting, and per-type counts — always inside one organization.

Documents are inserted directly (no upload), so these tests run no
processing and make no model calls."""

import hashlib
import os
import uuid

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.db.database import Database
from app.db.models import Document, DocumentStatus, DocumentVersion, FileType, User
from tests.integration.conftest import auth, register

pytestmark = pytest.mark.skipif(
    os.getenv("CONTRACTIQ_INTEGRATION") != "1", reason="set CONTRACTIQ_INTEGRATION=1"
)

LIBRARY_A = [
    ("Master Services Agreement", "contract.pdf", FileType.PDF, "application/pdf"),
    ("Scanned lease", "lease-scan.pdf", FileType.PDF, "application/pdf"),
    ("Invoice September", "invoice.jpg", FileType.IMAGE, "image/jpeg"),
    (
        "Leave policy",
        "policy.docx",
        FileType.WORD,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
    (
        "Vendor data",
        "data.xlsx",
        FileType.EXCEL,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ),
]


async def _seed(email: str, docs: list[tuple[str, str, FileType, str]]) -> None:
    db = Database(Settings())
    try:
        async with db.session_factory() as session:
            org_id = await session.scalar(select(User.organization_id).where(User.email == email))
            for title, filename, file_type, mime in docs:
                document = Document(
                    organization_id=org_id,
                    title=title,
                    file_type=file_type,
                    status=DocumentStatus.COMPLETED,
                    tags=[],
                )
                session.add(document)
                await session.flush()
                session.add(
                    DocumentVersion(
                        organization_id=org_id,
                        document_id=document.id,
                        version_number=1,
                        label="v1",
                        original_filename=filename,
                        storage_key=f"tenants/{org_id}/documents/{document.id}/seed",
                        mime_type=mime,
                        size_bytes=1024,
                        sha256=hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
                        status=DocumentStatus.COMPLETED,
                    )
                )
            await session.commit()
    finally:
        await db.dispose()


def _titles(response) -> list[str]:
    assert response.status_code == 200, response.text
    return [d["title"] for d in response.json()["data"]["items"]]


async def test_library_tabs_search_sort_and_counts(api, cleanup) -> None:
    tokens_a, email_a = register(api, cleanup, "Library A")
    _, email_b = register(api, cleanup, "Library B")
    await _seed(email_a, LIBRARY_A)
    await _seed(email_b, [("Company B secret", "invoice.jpg", FileType.IMAGE, "image/jpeg")])
    headers = auth(tokens_a)

    # All documents, and each tab, contain only this company's files.
    everything = _titles(api.get("/api/v1/documents", headers=headers))
    assert sorted(everything) == sorted(t for t, *_ in LIBRARY_A)
    images = api.get("/api/v1/documents", params={"file_type": "IMAGE"}, headers=headers)
    assert _titles(images) == ["Invoice September"]
    assert images.json()["data"]["items"][0]["file_type"] == "IMAGE"
    assert _titles(api.get("/api/v1/documents?file_type=PDF", headers=headers)) != []

    # Search matches the file name too, never another company's file.
    found = _titles(api.get("/api/v1/documents", params={"q": "invoice"}, headers=headers))
    assert found == ["Invoice September"]
    assert _titles(api.get("/api/v1/documents", params={"q": ".xlsx"}, headers=headers)) == [
        "Vendor data"
    ]
    assert _titles(api.get("/api/v1/documents", params={"q": "secret"}, headers=headers)) == []

    # Sorting by name, and paging without overlap.
    by_name = _titles(api.get("/api/v1/documents", params={"sort": "name"}, headers=headers))
    assert by_name == sorted(by_name, key=str.lower)
    first = _titles(
        api.get("/api/v1/documents", params={"sort": "name", "limit": 2}, headers=headers)
    )
    second = _titles(
        api.get(
            "/api/v1/documents", params={"sort": "name", "limit": 2, "offset": 2}, headers=headers
        )
    )
    assert first + second == by_name[:4]

    # Status filter takes several values (e.g. every in-progress stage).
    ready_or_failed = api.get(
        "/api/v1/documents", params=[("status", "COMPLETED"), ("status", "FAILED")], headers=headers
    )
    assert len(_titles(ready_or_failed)) == 5
    queued = api.get(
        "/api/v1/documents/facets",
        params=[("status", "QUEUED"), ("status", "EMBEDDING")],
        headers=headers,
    )
    assert queued.json()["data"]["all"] == 0

    # Tab counts.
    facets = api.get("/api/v1/documents/facets", headers=headers)
    assert facets.status_code == 200, facets.text
    data = facets.json()["data"]
    assert data["all"] == 5
    assert data["by_file_type"] == {"PDF": 2, "IMAGE": 1, "WORD": 1, "EXCEL": 1}
    searched = api.get("/api/v1/documents/facets", params={"q": "invoice"}, headers=headers)
    assert searched.json()["data"]["all"] == 1


def test_unknown_file_type_is_rejected(api, cleanup) -> None:
    tokens, _ = register(api, cleanup, "Library bad filter")
    response = api.get("/api/v1/documents", params={"file_type": "EXE"}, headers=auth(tokens))
    assert response.status_code == 422
