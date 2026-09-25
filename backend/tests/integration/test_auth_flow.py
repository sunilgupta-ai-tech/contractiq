"""
End-to-end authentication, RBAC and tenant isolation against real
PostgreSQL and Redis.

Run with the stack up (`make infra && make migrate`):
    CONTRACTIQ_INTEGRATION=1 pytest tests/integration
"""

import os

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.db.database import Database
from app.db.models import AuditLog, User
from tests.integration.conftest import PASSWORD, auth, new_email, register

pytestmark = pytest.mark.skipif(
    os.getenv("CONTRACTIQ_INTEGRATION") != "1", reason="set CONTRACTIQ_INTEGRATION=1"
)


def test_register_login_and_profile(api, cleanup):
    tokens, email = register(api, cleanup, "Org Alpha")

    me = api.get("/api/v1/users/me", headers=auth(tokens)).json()["data"]
    assert me["email"] == email and me["role"] == "ADMIN"
    assert "password_hash" not in me

    login = api.post("/api/v1/auth/login", json={"email": email.upper(), "password": PASSWORD})
    assert login.status_code == 200

    dup = api.post(
        "/api/v1/auth/register",
        json={"organization_name": "Org X", "full_name": "Y", "email": email, "password": PASSWORD},
    )
    assert dup.status_code == 409


def test_login_failures_are_indistinguishable(api, cleanup):
    _, email = register(api, cleanup, "Org Beta")
    wrong_pw = api.post("/api/v1/auth/login", json={"email": email, "password": "wrong-password"})
    no_user = api.post(
        "/api/v1/auth/login", json={"email": new_email("ghost"), "password": "wrong-password"}
    )
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json()["error"] == no_user.json()["error"]


def test_admin_manages_users_and_roles_are_enforced(api, cleanup):
    admin, _ = register(api, cleanup, "Org Gamma")
    viewer_email = new_email("viewer")
    created = api.post(
        "/api/v1/users",
        headers=auth(admin),
        json={"email": viewer_email, "full_name": "Vic", "password": PASSWORD, "role": "VIEWER"},
    )
    assert created.status_code == 201, created.text
    viewer_id = created.json()["data"]["id"]

    users = api.get("/api/v1/users", headers=auth(admin)).json()["data"]
    assert users["total"] == 2

    viewer = api.post(
        "/api/v1/auth/login", json={"email": viewer_email, "password": PASSWORD}
    ).json()["data"]
    assert api.get("/api/v1/users", headers=auth(viewer)).status_code == 403

    promoted = api.patch(
        f"/api/v1/users/{viewer_id}", headers=auth(admin), json={"role": "ANALYST"}
    )
    assert promoted.json()["data"]["role"] == "ANALYST"

    # Role changes reach the token at the next refresh.
    refreshed = api.post(
        "/api/v1/auth/refresh", json={"refresh_token": viewer["refresh_token"]}
    ).json()["data"]
    me = api.get("/api/v1/users/me", headers=auth(refreshed)).json()["data"]
    assert me["role"] == "ANALYST"

    # A deactivated user can no longer sign in or refresh.
    api.patch(f"/api/v1/users/{viewer_id}", headers=auth(admin), json={"is_active": False})
    login = api.post("/api/v1/auth/login", json={"email": viewer_email, "password": PASSWORD})
    assert login.status_code == 401
    again = api.post("/api/v1/auth/refresh", json={"refresh_token": refreshed["refresh_token"]})
    assert again.status_code == 401


def test_admin_cannot_see_or_touch_another_tenants_users(api, cleanup):
    admin_a, _ = register(api, cleanup, "Org A")
    admin_b, _ = register(api, cleanup, "Org B")
    user_b = api.get("/api/v1/users/me", headers=auth(admin_b)).json()["data"]

    response = api.patch(
        f"/api/v1/users/{user_b['id']}", headers=auth(admin_a), json={"role": "VIEWER"}
    )
    assert response.status_code == 404
    listed = api.get("/api/v1/users", headers=auth(admin_a)).json()["data"]["items"]
    assert user_b["id"] not in {u["id"] for u in listed}


def test_refresh_token_is_single_use(api, cleanup):
    tokens, _ = register(api, cleanup, "Org Delta")
    first = api.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert first.status_code == 200
    replay = api.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert replay.status_code == 401
    assert (
        api.post(
            "/api/v1/auth/refresh", json={"refresh_token": first.json()["data"]["refresh_token"]}
        ).status_code
        == 200
    )


async def test_auth_events_are_audited(api, cleanup):
    _, email = register(api, cleanup, "Org Epsilon")
    api.post("/api/v1/auth/login", json={"email": email, "password": "wrong-password"})
    api.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})

    db = Database(Settings())
    async with db.session_factory() as session:
        org_id = (
            await session.execute(select(User.organization_id).where(User.email == email))
        ).scalar_one()
        actions = (
            await session.execute(
                select(AuditLog.action)
                .where(AuditLog.organization_id == org_id)
                .order_by(AuditLog.created_at)
            )
        ).scalars()
        assert list(actions) == ["auth.register", "auth.login_failed", "auth.login"]
    await db.dispose()
