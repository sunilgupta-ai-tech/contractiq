"""Phase 18: the platform console — separate sign-in and audience, suspension
with immediate effect, plans and limits, read-only support admins, audit."""

import os
import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete

from app.core.config import Settings
from app.core.security import hash_password
from app.db.database import Database
from app.db.models import PlatformAdmin, PlatformAuditLog, PlatformRole
from tests.integration.conftest import PASSWORD, auth, new_email, register

pytestmark = pytest.mark.skipif(
    os.getenv("CONTRACTIQ_INTEGRATION") != "1", reason="set CONTRACTIQ_INTEGRATION=1"
)

API = "/api/v1"
P = f"{API}/platform"


@pytest.fixture
async def platform_admins() -> AsyncIterator[dict[PlatformRole, str]]:
    """One SUPER_ADMIN and one SUPPORT admin; emails by role. Removed after."""
    db = Database(Settings())
    emails = {
        role: f"pa-{role.value.lower()}-{uuid.uuid4().hex[:8]}@docunexa.test"
        for role in PlatformRole
    }
    async with db.session_factory() as s:
        for role, email in emails.items():
            s.add(
                PlatformAdmin(
                    email=email,
                    full_name=role.value,
                    password_hash=hash_password(PASSWORD),
                    role=role,
                )
            )
        await s.commit()
    yield emails
    async with db.session_factory() as s:
        ids = [
            a.id
            for a in (
                await s.execute(
                    PlatformAdmin.__table__.select().where(
                        PlatformAdmin.email.in_(list(emails.values()))
                        | PlatformAdmin.email.like("pa-new-%")
                    )
                )
            ).all()
        ]
        await s.execute(delete(PlatformAuditLog).where(PlatformAuditLog.actor_id.in_(ids)))
        await s.execute(delete(PlatformAdmin).where(PlatformAdmin.id.in_(ids)))
        await s.commit()
    await db.dispose()


def _platform_login(api, email: str) -> dict:
    response = api.post(f"{P}/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _org_id(api, tokens) -> str:
    return api.get(f"{API}/users/me", headers=auth(tokens)).json()["data"]["organization_id"]


def test_tenant_and_platform_tokens_do_not_cross(api, cleanup, platform_admins):
    tenant, _ = register(api, cleanup, "Crossing Org")
    platform = _platform_login(api, platform_admins[PlatformRole.SUPER_ADMIN])
    assert api.get(f"{P}/overview", headers=auth(tenant)).status_code == 401
    assert api.get(f"{API}/documents", headers=auth(platform)).status_code == 401
    assert api.get(f"{API}/users/me", headers=auth(platform)).status_code == 401
    # An organization user's credentials do not open the console.
    tenant_email = cleanup[-1]
    wrong = api.post(f"{P}/auth/login", json={"email": tenant_email, "password": PASSWORD})
    assert wrong.status_code == 401


def test_console_lists_organizations_with_usage(api, cleanup, platform_admins):
    tenant, email = register(api, cleanup, "Usage Org")
    org_id = _org_id(api, tenant)
    platform = _platform_login(api, platform_admins[PlatformRole.SUPPORT])

    overview = api.get(f"{P}/overview", headers=auth(platform)).json()["data"]
    assert overview["organizations"] >= 1 and overview["users"] >= 1

    # Found by a member's email; usage and the default plan are shown.
    found = api.get(f"{P}/organizations", params={"q": email}, headers=auth(platform)).json()[
        "data"
    ]
    (org,) = found["items"]
    assert org["id"] == org_id and org["status"] == "ACTIVE" and org["plan"] == "FREE"
    assert org["usage"]["active_users"] == 1 and org["limits"]["max_users"] == 5

    detail = api.get(f"{P}/organizations/{org_id}", headers=auth(platform)).json()["data"]
    assert [m["role_name"] for m in detail["members"]] == ["Admin"]
    assert set(detail["documents_by_type"]) == {"PDF", "IMAGE", "WORD", "EXCEL"}
    # Accounts and counts only: no document titles, content or answers.
    assert not {"documents", "chunks", "conversations"} & set(detail)


def test_suspension_ends_sessions_and_blocks_sign_in(api, cleanup, platform_admins):
    tenant, email = register(api, cleanup, "Suspended Org")
    org_id = _org_id(api, tenant)
    platform = _platform_login(api, platform_admins[PlatformRole.SUPER_ADMIN])

    no_reason = api.patch(
        f"{P}/organizations/{org_id}", json={"status": "SUSPENDED"}, headers=auth(platform)
    )
    assert no_reason.status_code == 422
    suspended = api.patch(
        f"{P}/organizations/{org_id}",
        json={"status": "SUSPENDED", "suspended_reason": "Unpaid invoice"},
        headers=auth(platform),
    )
    assert suspended.status_code == 200, suspended.text
    assert suspended.json()["data"]["suspended_reason"] == "Unpaid invoice"

    # The open session ends at once, refresh and sign-in are refused.
    assert api.get(f"{API}/documents", headers=auth(tenant)).status_code == 401
    refresh = api.post(f"{API}/auth/refresh", json={"refresh_token": tenant["refresh_token"]})
    assert refresh.status_code == 401
    login = api.post(f"{API}/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 403
    assert login.json()["error"]["code"] == "ORGANIZATION_SUSPENDED"

    api.patch(f"{P}/organizations/{org_id}", json={"status": "ACTIVE"}, headers=auth(platform))
    assert (
        api.post(f"{API}/auth/login", json={"email": email, "password": PASSWORD}).status_code
        == 200
    )


def test_plan_limits_are_enforced_and_plans_reset_limits(api, cleanup, platform_admins):
    tenant, _ = register(api, cleanup, "Limited Org")
    org_id = _org_id(api, tenant)
    platform = _platform_login(api, platform_admins[PlatformRole.SUPER_ADMIN])

    api.patch(f"{P}/organizations/{org_id}", json={"max_users": 1}, headers=auth(platform))
    email = new_email("limited")
    cleanup.append(email)
    blocked = api.post(
        f"{API}/users",
        json={"email": email, "full_name": "Extra", "password": PASSWORD},
        headers=auth(tenant),
    )
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "PLAN_LIMIT_REACHED"

    upgraded = api.patch(
        f"{P}/organizations/{org_id}", json={"plan": "STARTER"}, headers=auth(platform)
    ).json()["data"]
    assert upgraded["plan"] == "STARTER" and upgraded["limits"]["max_users"] == 25
    added = api.post(
        f"{API}/users",
        json={"email": email, "full_name": "Extra", "password": PASSWORD},
        headers=auth(tenant),
    )
    assert added.status_code == 201

    unlimited = api.patch(
        f"{P}/organizations/{org_id}", json={"unlimited": ["max_documents"]}, headers=auth(platform)
    ).json()["data"]
    assert unlimited["limits"]["max_documents"] is None


def test_support_admins_are_read_only(api, cleanup, platform_admins):
    tenant, _ = register(api, cleanup, "Support Org")
    org_id = _org_id(api, tenant)
    support = _platform_login(api, platform_admins[PlatformRole.SUPPORT])
    assert api.get(f"{P}/organizations/{org_id}", headers=auth(support)).status_code == 200
    change = api.patch(
        f"{P}/organizations/{org_id}", json={"plan": "ENTERPRISE"}, headers=auth(support)
    )
    assert change.status_code == 403
    assert api.get(f"{P}/admins", headers=auth(support)).status_code == 403


def test_super_admin_manages_platform_admins_and_actions_are_audited(api, cleanup, platform_admins):
    platform = _platform_login(api, platform_admins[PlatformRole.SUPER_ADMIN])
    me = api.get(f"{P}/me", headers=auth(platform)).json()["data"]
    created = api.post(
        f"{P}/admins",
        json={
            "email": f"pa-new-{uuid.uuid4().hex[:8]}@docunexa.test",
            "full_name": "New support",
            "password": PASSWORD,
        },
        headers=auth(platform),
    )
    assert created.status_code == 201 and created.json()["data"]["role"] == "SUPPORT"
    new_id = created.json()["data"]["id"]
    new_tokens = _platform_login(api, created.json()["data"]["email"])

    # Deactivating an admin ends their session at once.
    off = api.patch(f"{P}/admins/{new_id}", json={"is_active": False}, headers=auth(platform))
    assert off.status_code == 200
    assert api.get(f"{P}/overview", headers=auth(new_tokens)).status_code == 401
    # Nobody changes their own role or status.
    own = api.patch(f"{P}/admins/{me['id']}", json={"role": "SUPPORT"}, headers=auth(platform))
    assert own.status_code == 403

    audit = api.get(f"{P}/audit", headers=auth(platform)).json()["data"]["items"]
    actions = {a["action"] for a in audit if a["actor_id"] == me["id"]}
    assert {"platform.login", "platform_admin.create", "platform_admin.update"} <= actions
