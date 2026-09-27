"""Phase 17: system and custom roles, permission checks, escalation rules
and immediate revocation, end to end against the running stack."""

import os
import uuid

import pytest

from tests.integration.conftest import PASSWORD, auth, new_email, register

pytestmark = pytest.mark.skipif(
    os.getenv("CONTRACTIQ_INTEGRATION") != "1", reason="set CONTRACTIQ_INTEGRATION=1"
)

API = "/api/v1"


def _roles(api, tokens) -> dict[str, dict]:
    response = api.get(f"{API}/roles", headers=auth(tokens))
    assert response.status_code == 200, response.text
    return {r["name"]: r for r in response.json()["data"]}


def _add_user(api, admin_tokens, cleanup, role_id) -> tuple[dict, str]:
    """Create a user with `role_id` and sign them in; returns (tokens, user id)."""
    email = new_email("member")
    cleanup.append(email)
    created = api.post(
        f"{API}/users",
        json={"email": email, "full_name": "Member", "password": PASSWORD, "role_id": role_id},
        headers=auth(admin_tokens),
    )
    assert created.status_code == 201, created.text
    login = api.post(f"{API}/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return login.json()["data"], created.json()["data"]["id"]


def _create_role(api, tokens, name, permissions):
    return api.post(
        f"{API}/roles",
        json={"name": name, "description": "test", "permissions": permissions},
        headers=auth(tokens),
    )


def test_system_roles_and_permission_catalog(api, cleanup):
    admin, _ = register(api, cleanup, "Roles basics")
    roles = _roles(api, admin)
    assert list(roles) == ["Admin", "Manager", "Employee", "Viewer"]
    assert all(r["is_system"] for r in roles.values())
    assert roles["Admin"]["member_count"] == 1
    catalog = api.get(f"{API}/permissions", headers=auth(admin)).json()["data"]
    assert {p["key"] for p in catalog} >= {"document:upload", "user:manage", "role:manage"}
    me = api.get(f"{API}/users/me", headers=auth(admin)).json()["data"]
    assert me["role_name"] == "Admin" and "role:manage" in me["permissions"]


def test_custom_role_applies_and_changes_take_effect_immediately(api, cleanup):
    admin, _ = register(api, cleanup, "Roles custom")
    created = _create_role(api, admin, "Auditor", ["document:read"])
    assert created.status_code == 201, created.text
    auditor = created.json()["data"]
    member, _ = _add_user(api, admin, cleanup, auditor["id"])

    # Reading is allowed; asking questions is not (not in the role).
    assert api.get(f"{API}/documents", headers=auth(member)).status_code == 200
    ask = api.post(f"{API}/query", json={"question": "Anything?"}, headers=auth(member))
    assert ask.status_code == 403

    # Granting a permission revokes existing access tokens at once...
    updated = api.patch(
        f"{API}/roles/{auditor['id']}",
        json={"permissions": ["document:read", "query:run"]},
        headers=auth(admin),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["member_count"] == 1
    stale = api.get(f"{API}/documents", headers=auth(member))
    assert stale.status_code == 401
    # ...and a refresh picks up the new permissions.
    refreshed = api.post(
        f"{API}/auth/refresh", json={"refresh_token": member["refresh_token"]}
    ).json()["data"]
    me = api.get(f"{API}/users/me", headers=auth(refreshed)).json()["data"]
    assert me["role_name"] == "Auditor" and set(me["permissions"]) == {"document:read", "query:run"}


def test_role_management_cannot_escalate(api, cleanup):
    admin, _ = register(api, cleanup, "Roles escalation")
    lead_role = _create_role(
        api, admin, "Team lead", ["document:read", "user:manage", "role:manage"]
    ).json()["data"]
    lead, _ = _add_user(api, admin, cleanup, lead_role["id"])
    admin_id = api.get(f"{API}/users/me", headers=auth(admin)).json()["data"]["id"]
    roles = _roles(api, lead)

    # Cannot create a role with access the lead does not have...
    beyond = _create_role(api, lead, "Deleter", ["document:read", "document:delete"])
    assert beyond.status_code == 403
    # ...nor edit their own role to gain it...
    own = api.patch(
        f"{API}/roles/{lead_role['id']}",
        json={"permissions": ["document:read", "document:delete"]},
        headers=auth(lead),
    )
    assert own.status_code == 403
    # ...nor assign the Admin role, nor change the Admin.
    promote = _add_user_raw(api, lead, cleanup, roles["Admin"]["id"])
    assert promote.status_code == 403
    demote = api.patch(
        f"{API}/users/{admin_id}", json={"role_id": roles["Viewer"]["id"]}, headers=auth(lead)
    )
    assert demote.status_code == 403
    # Within their own access, they can manage roles and users.
    reader = _create_role(api, lead, "Reader", ["document:read"])
    assert reader.status_code == 201
    assert _add_user_raw(api, lead, cleanup, reader.json()["data"]["id"]).status_code == 201


def _add_user_raw(api, tokens, cleanup, role_id):
    email = new_email("raw")
    cleanup.append(email)
    return api.post(
        f"{API}/users",
        json={"email": email, "full_name": "Raw", "password": PASSWORD, "role_id": role_id},
        headers=auth(tokens),
    )


def test_system_roles_are_locked_and_used_roles_cannot_be_deleted(api, cleanup):
    admin, _ = register(api, cleanup, "Roles locked")
    roles = _roles(api, admin)
    locked = api.patch(
        f"{API}/roles/{roles['Viewer']['id']}", json={"name": "Reader"}, headers=auth(admin)
    )
    assert locked.status_code == 403
    assert (
        api.delete(f"{API}/roles/{roles['Viewer']['id']}", headers=auth(admin)).status_code == 403
    )

    in_use = _create_role(api, admin, "Contractor", ["document:read"]).json()["data"]
    _add_user(api, admin, cleanup, in_use["id"])
    conflict = api.delete(f"{API}/roles/{in_use['id']}", headers=auth(admin))
    assert conflict.status_code == 409
    unused = _create_role(api, admin, "Temp", ["document:read"]).json()["data"]
    assert api.delete(f"{API}/roles/{unused['id']}", headers=auth(admin)).status_code == 204
    # Names are unique, including the system names.
    assert _create_role(api, admin, "viewer", ["document:read"]).status_code == 409


def test_custom_roles_are_private_to_their_organization(api, cleanup):
    admin_a, _ = register(api, cleanup, "Roles A")
    admin_b, _ = register(api, cleanup, "Roles B")
    secret = _create_role(api, admin_a, "A only", ["document:read"]).json()["data"]
    assert "A only" not in _roles(api, admin_b)
    foreign = _add_user_raw(api, admin_b, cleanup, secret["id"])
    assert foreign.status_code == 404
    edit = api.patch(f"{API}/roles/{secret['id']}", json={"name": "Mine"}, headers=auth(admin_b))
    assert edit.status_code == 404


def test_deactivating_a_user_ends_their_session_at_once(api, cleanup):
    admin, _ = register(api, cleanup, "Roles deactivate")
    viewer_id = _roles(api, admin)["Viewer"]["id"]
    member, member_id = _add_user(api, admin, cleanup, viewer_id)
    assert api.get(f"{API}/documents", headers=auth(member)).status_code == 200
    off = api.patch(f"{API}/users/{member_id}", json={"is_active": False}, headers=auth(admin))
    assert off.status_code == 200 and off.json()["data"]["is_active"] is False
    assert api.get(f"{API}/documents", headers=auth(member)).status_code == 401
    refresh = api.post(f"{API}/auth/refresh", json={"refresh_token": member["refresh_token"]})
    assert refresh.status_code == 401


def test_unknown_role_is_not_found(api, cleanup):
    admin, _ = register(api, cleanup, "Roles unknown")
    assert _add_user_raw(api, admin, cleanup, str(uuid.uuid4())).status_code == 404
