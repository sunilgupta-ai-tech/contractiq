import time
import uuid

import jwt
import pytest
from pydantic import ValidationError
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core.config import Settings
from app.core.exceptions import UnauthorizedError
from app.core.security import (
    PERMISSION_INFO,
    SYSTEM_ROLE_PERMISSIONS,
    TENANT_AUDIENCE,
    Permission,
    SystemRole,
    decode_token,
    hash_password,
    parse_permissions,
    verify_password,
)
from app.core.sessions import revoke_org_sessions, revoke_user_sessions, token_is_current
from tests.tokens import token_for


def test_password_hash_roundtrip():
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong", hashed)


def test_token_roundtrip_carries_tenant_and_permissions(settings):
    tenant = str(uuid.uuid4())
    token = token_for(settings, SystemRole.EMPLOYEE, tenant_id=tenant)
    claims = decode_token(settings, token)
    assert claims["tid"] == tenant and claims["role"] == "Employee"
    assert claims["aud"] == TENANT_AUDIENCE
    assert parse_permissions(claims["perms"]) == SYSTEM_ROLE_PERMISSIONS[SystemRole.EMPLOYEE]


def test_tokens_without_the_tenant_audience_are_rejected(settings):
    token = jwt.encode(
        {
            "sub": "u",
            "tid": "t",
            "aud": "docunexa:platform",
            "role": "Admin",
            "rid": "r",
            "perms": [],
            "type": "access",
            "ts": 1,
            "exp": 9999999999,
        },
        settings.jwt_secret_key.get_secret_value(),
        algorithm="HS256",
    )
    with pytest.raises(UnauthorizedError):
        decode_token(settings, token)


def test_unknown_permissions_in_tokens_are_ignored():
    assert parse_permissions(["query:run", "retired:permission"]) == {Permission.QUERY_RUN}


def test_every_permission_is_described():
    assert set(PERMISSION_INFO) == set(Permission)


def test_refresh_token_rejected_as_access(settings):
    token = token_for(settings, token_type="refresh")
    with pytest.raises(UnauthorizedError):
        decode_token(settings, token, expected_type="access")


def test_forged_token_rejected(settings):
    forged = jwt.encode(
        {"sub": "u", "tid": "other-tenant", "role": "ADMIN", "type": "access", "exp": 9999999999},
        "attacker-key",
        algorithm="HS256",
    )
    with pytest.raises(UnauthorizedError):
        decode_token(settings, forged)


@pytest.mark.parametrize(
    ("role", "permission", "allowed"),
    [
        (SystemRole.VIEWER, Permission.QUERY_RUN, True),
        (SystemRole.VIEWER, Permission.DOCUMENT_UPLOAD, False),
        (SystemRole.EMPLOYEE, Permission.DOCUMENT_UPLOAD, True),
        (SystemRole.EMPLOYEE, Permission.DOCUMENT_DELETE, False),
        (SystemRole.MANAGER, Permission.DOCUMENT_DELETE, True),
        (SystemRole.MANAGER, Permission.USER_MANAGE, False),
        (SystemRole.MANAGER, Permission.ROLE_MANAGE, False),
        (SystemRole.ADMIN, Permission.USER_MANAGE, True),
        (SystemRole.ADMIN, Permission.ROLE_MANAGE, True),
    ],
)
def test_rbac_matrix(role, permission, allowed):
    assert (permission in SYSTEM_ROLE_PERMISSIONS[role]) is allowed


def test_production_refuses_default_jwt_secret():
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        Settings(app_env="production")


def test_production_refuses_wildcard_cors():
    with pytest.raises(ValidationError, match="CORS"):
        Settings(app_env="production", jwt_secret_key="x" * 64, cors_origins=["*"])


def test_cors_origins_parse_from_comma_string():
    assert Settings(cors_origins="https://a.com, https://b.com").cors_origins == [
        "https://a.com",
        "https://b.com",
    ]


def test_secrets_not_in_repr():
    s = Settings(gemini_api_key="super-secret-key")
    assert "super-secret-key" not in repr(s)


def test_cors_origins_parse_from_environment(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com,https://admin.example.com")
    assert Settings().cors_origins == ["https://app.example.com", "https://admin.example.com"]
    monkeypatch.setenv("CORS_ORIGINS", '["https://json.example.com"]')
    assert Settings().cors_origins == ["https://json.example.com"]


# --- Immediate revocation (Phase 17) ------------------------------------------------


class _MarkRedis:
    def __init__(self, fail=False):
        self.data: dict[str, str] = {}
        self.fail = fail

    async def set(self, key, value, ex=None):
        self.data[key] = str(value)

    async def mget(self, *keys):
        if self.fail:
            raise RedisConnectionError("down")
        return [self.data.get(k) for k in keys]


async def test_tokens_issued_before_a_change_are_stale():
    redis = _MarkRedis()
    user, org = uuid.uuid4(), uuid.uuid4()
    before = int(time.time() * 1000) - 5
    assert await token_is_current(redis, user_id=str(user), tenant_id=str(org), ts=before)
    await revoke_user_sessions(redis, user, ttl_s=60)
    assert not await token_is_current(redis, user_id=str(user), tenant_id=str(org), ts=before)
    later = int(time.time() * 1000) + 5
    assert await token_is_current(redis, user_id=str(user), tenant_id=str(org), ts=later)
    # An organization-wide change affects every member.
    other = uuid.uuid4()
    await revoke_org_sessions(redis, org, ttl_s=60)
    assert not await token_is_current(redis, user_id=str(other), tenant_id=str(org), ts=before)


async def test_session_check_is_skipped_without_redis():
    assert await token_is_current(None, user_id="u", tenant_id="t", ts=0)
    assert await token_is_current(_MarkRedis(fail=True), user_id="u", tenant_id="t", ts=0)
