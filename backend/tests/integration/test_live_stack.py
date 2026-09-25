"""
Integration tests against real PostgreSQL, Redis and Qdrant.

Run with the stack up (`make infra && make migrate`):
    CONTRACTIQ_INTEGRATION=1 pytest tests/integration
"""

import os
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.exceptions import NotFoundError
from app.db.database import Database
from app.db.models import Document, Organization
from app.db.repositories.document_repository import DocumentRepository
from app.main import create_app

pytestmark = pytest.mark.skipif(
    os.getenv("CONTRACTIQ_INTEGRATION") != "1", reason="set CONTRACTIQ_INTEGRATION=1"
)


def test_ready_against_real_dependencies():
    settings = Settings()
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/ready")
    assert response.status_code == 200, response.text
    deps = {d["name"]: d["status"] for d in response.json()["data"]["dependencies"]}
    assert {k: deps[k] for k in ("postgres", "redis", "qdrant")} == {
        "postgres": "up",
        "redis": "up",
        "qdrant": "up",
    }
    assert "worker" in deps  # non-critical; up only when a worker is running


async def test_qdrant_collection_bootstrapped_with_tenant_index():
    settings = Settings()
    with TestClient(create_app(settings)):
        pass
    from app.vectorstore.qdrant import create_qdrant

    qdrant = create_qdrant(settings)
    info = await qdrant.get_collection(settings.qdrant_collection)
    assert "tenant_id" in info.payload_schema
    assert "dense" in info.config.params.vectors
    await qdrant.close()


async def test_repository_never_crosses_tenants():
    db = Database(Settings())
    async with db.session_factory() as session:
        org_a = Organization(name="Org A", slug=f"a-{uuid.uuid4().hex[:8]}")
        org_b = Organization(name="Org B", slug=f"b-{uuid.uuid4().hex[:8]}")
        session.add_all([org_a, org_b])
        await session.flush()

        doc_b = await DocumentRepository(session, org_b.id).add(Document(title="B's MSA"))
        repo_a = DocumentRepository(session, org_a.id)

        with pytest.raises(NotFoundError):
            await repo_a.get(doc_b.id)
        assert await repo_a.count() == 0
        assert await DocumentRepository(session, org_b.id).count() == 1
        await session.rollback()
    await db.dispose()
