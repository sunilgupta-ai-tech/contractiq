"""Shared fixtures for integration tests against the real stack."""

import shutil
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core.config import Settings
from app.db.database import Database
from app.db.models import Organization, User
from app.main import create_app

PASSWORD = "correct horse battery staple"


@pytest.fixture
def api() -> Iterator[TestClient]:
    with TestClient(create_app(Settings())) as client:
        yield client


@pytest.fixture
async def cleanup() -> AsyncIterator[list[str]]:
    """Collects registered emails; afterwards deletes their organizations
    (cascading to users, documents, jobs and audit rows) and their stored
    files, so tests leave nothing behind."""
    emails: list[str] = []
    yield emails
    settings = Settings()
    db = Database(settings)
    async with db.session_factory() as session:
        org_ids = list(
            (
                await session.execute(select(User.organization_id).where(User.email.in_(emails)))
            ).scalars()
        )
        await session.execute(delete(Organization).where(Organization.id.in_(org_ids)))
        await session.commit()
    await db.dispose()
    for org_id in org_ids:
        shutil.rmtree(Path(settings.local_storage_path) / "tenants" / str(org_id), True)


def new_email(tag: str) -> str:
    return f"it-{tag}-{uuid.uuid4().hex[:10]}@contractiq.test"


def register(api: TestClient, cleanup: list[str], org: str) -> tuple[dict, str]:
    """Register a new organization; returns its ADMIN's token pair and email."""
    email = new_email("admin")
    cleanup.append(email)
    response = api.post(
        "/api/v1/auth/register",
        json={"organization_name": org, "full_name": "Admin", "email": email, "password": PASSWORD},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"], email


def auth(tokens: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['access_token']}"}
