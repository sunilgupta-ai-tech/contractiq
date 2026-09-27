"""Phase 22: invitations, AI usage accounting and limits, audit of AI
questions and downloads, and organization deletion — end to end. No model
is called: limits are checked before any model call, and usage is recorded
through the same code the pipelines use."""

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.core.config import Settings
from app.db.database import Database
from app.db.models import Invitation, Organization, OrganizationStatus, PlatformRole, User
from app.db.tenancy import bind_tenant
from app.services import usage
from app.storage import create_storage
from tests.integration.conftest import PASSWORD, auth, new_email, register
from tests.integration.test_platform_flow import _platform_login

pytestmark = pytest.mark.skipif(
    os.getenv("CONTRACTIQ_INTEGRATION") != "1", reason="set CONTRACTIQ_INTEGRATION=1"
)

API = "/api/v1"


def _roles(api, tokens) -> dict[str, str]:
    return {
        r["name"]: r["id"] for r in api.get(f"{API}/roles", headers=auth(tokens)).json()["data"]
    }


async def _org_id(email: str) -> uuid.UUID:
    db = Database(Settings())
    async with db.session_factory() as s:
        org = await s.scalar(select(User.organization_id).where(User.email == email))
    await db.dispose()
    return org


# --- Invitations -----------------------------------------------------------------------


def test_invite_preview_accept_and_single_use(api, cleanup):
    admin, _ = register(api, cleanup, "Invite Org")
    email = new_email("invited")
    cleanup.append(email)
    created = api.post(
        f"{API}/invitations",
        json={"email": email, "role_id": _roles(api, admin)["Employee"]},
        headers=auth(admin),
    )
    assert created.status_code == 201, created.text
    token = created.json()["data"]["token"]
    assert [
        i["email"] for i in api.get(f"{API}/invitations", headers=auth(admin)).json()["data"]
    ] == [email]

    preview = api.get(f"{API}/auth/invitations/{token}").json()["data"]
    assert preview == {
        **preview,
        "email": email,
        "organization_name": "Invite Org",
        "role_name": "Employee",
    }

    accepted = api.post(
        f"{API}/auth/invitations/{token}/accept",
        json={"full_name": "New Person", "password": PASSWORD},
    )
    assert accepted.status_code == 201, accepted.text
    me = api.get(f"{API}/users/me", headers=auth(accepted.json()["data"])).json()["data"]
    assert me["email"] == email and me["role_name"] == "Employee"

    # Used once; unknown tokens reveal nothing.
    again = api.post(
        f"{API}/auth/invitations/{token}/accept", json={"full_name": "X", "password": PASSWORD}
    )
    assert again.status_code == 404
    assert api.get(f"{API}/auth/invitations/not-a-token").status_code == 404
    assert api.get(f"{API}/invitations", headers=auth(admin)).json()["data"] == []


async def test_revoked_and_expired_invitations_do_not_work(api, cleanup):
    admin, _ = register(api, cleanup, "Invite Expired")
    roles = _roles(api, admin)
    first = api.post(
        f"{API}/invitations",
        json={"email": new_email("r"), "role_id": roles["Viewer"]},
        headers=auth(admin),
    ).json()["data"]
    assert api.delete(f"{API}/invitations/{first['id']}", headers=auth(admin)).status_code == 204
    assert api.get(f"{API}/auth/invitations/{first['token']}").status_code == 404

    second = api.post(
        f"{API}/invitations",
        json={"email": new_email("e"), "role_id": roles["Viewer"]},
        headers=auth(admin),
    ).json()["data"]
    db = Database(Settings())
    async with db.session_factory() as s:
        await s.execute(
            update(Invitation)
            .where(Invitation.id == uuid.UUID(second["id"]))
            .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        await s.commit()
    await db.dispose()
    assert api.get(f"{API}/auth/invitations/{second['token']}").status_code == 404


def test_invitations_follow_the_no_escalation_rule(api, cleanup):
    admin, _ = register(api, cleanup, "Invite Escalation")
    lead_role = api.post(
        f"{API}/roles",
        json={"name": "Lead", "permissions": ["document:read", "user:manage"]},
        headers=auth(admin),
    ).json()["data"]
    email = new_email("lead")
    cleanup.append(email)
    api.post(
        f"{API}/users",
        json={
            "email": email,
            "full_name": "Lead",
            "password": PASSWORD,
            "role_id": lead_role["id"],
        },
        headers=auth(admin),
    )
    lead = api.post(f"{API}/auth/login", json={"email": email, "password": PASSWORD}).json()["data"]
    beyond = api.post(
        f"{API}/invitations",
        json={"email": new_email("x"), "role_id": _roles(api, admin)["Admin"]},
        headers=auth(lead),
    )
    assert beyond.status_code == 403


# --- AI usage and limits ---------------------------------------------------------------


async def test_usage_is_recorded_per_month_and_limits_stop_questions(api, cleanup):
    admin, email = register(api, cleanup, "Usage Org")
    org_id = await _org_id(email)
    db = Database(Settings())
    async with db.session_factory() as session:
        await bind_tenant(session, org_id)
        meter = usage.AIMeter(session, org_id)

        async def work() -> str:
            usage.add_llm(1200, 80)  # what the monitoring wrapper reports per call
            usage.add_embedding(40)
            return "done"

        assert await meter.run(work, queries=1) == "done"
        assert await meter.run(work, queries=1) == "done"
    await db.dispose()

    report = api.get(f"{API}/usage", headers=auth(admin)).json()["data"]
    month = report["months"][0]
    assert month["period"] == usage.current_period()
    assert (month["queries"], month["prompt_tokens"], month["completion_tokens"]) == (2, 2400, 160)
    assert month["embedding_tokens"] == 80 and month["model_calls"] == 2
    assert report["plan"] == "FREE" and report["limits"]["max_ai_queries_month"] == 500

    # With the monthly allowance used up, questions stop before any model call.
    db = Database(Settings())
    async with db.session_factory() as s:
        await s.execute(
            update(Organization).where(Organization.id == org_id).values(max_ai_queries_month=2)
        )
        await s.commit()
    await db.dispose()
    blocked = api.post(
        f"{API}/query", json={"question": "What is the notice period?"}, headers=auth(admin)
    )
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "PLAN_LIMIT_REACHED"


# --- Audit: downloads and the log --------------------------------------------------------


def test_downloads_are_streamed_and_audited(api, cleanup):
    admin, _ = register(api, cleanup, "Audit Org")
    data = f"%PDF-1.7\n% {uuid.uuid4()}\n%%EOF\n".encode()
    uploaded = api.post(
        f"{API}/documents/upload",
        headers=auth(admin),
        files={"file": ("Board pack é.pdf", data, "application/pdf")},
    ).json()["data"]
    doc_id, version_id = uploaded["document"]["id"], uploaded["version"]["id"]
    download = api.get(
        f"{API}/documents/{doc_id}/versions/{version_id}/download", headers=auth(admin)
    )
    assert download.status_code == 200 and download.content == data
    assert "filename*=UTF-8''Board%20pack%20%C3%A9.pdf" in download.headers["content-disposition"]

    log = api.get(f"{API}/audit-logs", params={"action": "document."}, headers=auth(admin)).json()[
        "data"
    ]
    actions = [e["action"] for e in log["items"]]
    assert "document.download" in actions and "document.upload" in actions
    assert all(e["actor_name"] for e in log["items"])

    viewer_email = new_email("viewer")
    cleanup.append(viewer_email)
    api.post(
        f"{API}/users",
        json={"email": viewer_email, "full_name": "V", "password": PASSWORD},
        headers=auth(admin),
    )
    viewer = api.post(
        f"{API}/auth/login", json={"email": viewer_email, "password": PASSWORD}
    ).json()["data"]
    assert api.get(f"{API}/audit-logs", headers=auth(viewer)).status_code == 403


# --- Organization deletion ---------------------------------------------------------------


async def test_deleting_an_organization_ends_access_and_removes_its_rows(
    api, cleanup, platform_admins
):  # noqa: F811
    tenant, email = register(api, cleanup, "Doomed Org")
    org_id = await _org_id(email)
    uploaded = api.post(
        f"{API}/documents/upload",
        headers=auth(tenant),
        files={"file": ("x.pdf", f"%PDF-1.7\n% {uuid.uuid4()}\n".encode(), "application/pdf")},
    )
    assert uploaded.status_code == 202
    platform = _platform_login(api, platform_admins[PlatformRole.SUPER_ADMIN])

    wrong = api.request(
        "DELETE",
        f"{API}/platform/organizations/{org_id}",
        json={"confirm_name": "Doomed"},
        headers=auth(platform),
    )
    assert wrong.status_code == 409
    done = api.request(
        "DELETE",
        f"{API}/platform/organizations/{org_id}",
        json={"confirm_name": "Doomed Org"},
        headers=auth(platform),
    )
    assert done.status_code == 202

    # Access ends at once...
    assert api.get(f"{API}/documents", headers=auth(tenant)).status_code == 401
    login = api.post(f"{API}/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code in (401, 403)

    # ...and the running worker erases the data in the background.
    db = Database(Settings())
    for _ in range(60):
        async with db.session_factory() as s:
            org = await s.get(Organization, org_id)
        if org is None:
            break
        assert org.status is OrganizationStatus.DELETING
        await asyncio.sleep(0.5)
    await db.dispose()
    assert org is None, "the worker did not delete the organization"
    db = Database(Settings())
    async with db.session_factory() as s:
        assert await s.scalar(select(User.id).where(User.email == email)) is None  # cascaded
    await db.dispose()


async def test_erasure_removes_files_vectors_and_cache_of_one_tenant_only():
    """What the deletion job runs: files, vectors and cache entries of the
    tenant go; another tenant's stay."""
    from types import SimpleNamespace

    from redis.asyncio import Redis

    from app.services.erasure import erase_tenant_data
    from app.vectorstore.collections import ensure_collection
    from app.vectorstore.indexing import upsert_version
    from app.vectorstore.qdrant import create_qdrant, tenant_filter
    from tests.integration.test_vector_index import _points, _target

    settings = Settings()
    doomed, kept = str(uuid.uuid4()), str(uuid.uuid4())
    storage = create_storage(settings)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    client = create_qdrant(settings)
    collection = f"test_chunks_{uuid.uuid4().hex[:10]}"
    await ensure_collection(client, collection, 768)
    try:
        for tenant in (doomed, kept):
            await storage.put(
                f"tenants/{tenant}/documents/d/v/original.pdf", b"%PDF", "application/pdf"
            )
            await redis.set(f"ciq:{tenant}:emb:x", "1")
            target = _target(tenant=tenant, document=f"d-{tenant[:4]}")
            await upsert_version(client, collection, target, _points(target)[0])
        resources = SimpleNamespace(
            qdrant=client,
            storage=storage,
            redis=redis,
            settings=settings.model_copy(update={"qdrant_collection": collection}),
        )
        await erase_tenant_data(resources, doomed)  # type: ignore[arg-type]

        assert not await storage.exists(f"tenants/{doomed}/documents/d/v/original.pdf")
        assert await storage.exists(f"tenants/{kept}/documents/d/v/original.pdf")
        assert await redis.get(f"ciq:{doomed}:emb:x") is None
        assert await redis.get(f"ciq:{kept}:emb:x") == "1"
        count = lambda t: client.count(collection, count_filter=tenant_filter(t), exact=True)  # noqa: E731
        assert (await count(doomed)).count == 0 and (await count(kept)).count > 0
    finally:
        await storage.delete_prefix(f"tenants/{kept}/")
        await redis.delete(f"ciq:{kept}:emb:x")
        await redis.aclose()
        await client.delete_collection(collection)
        await client.close()
