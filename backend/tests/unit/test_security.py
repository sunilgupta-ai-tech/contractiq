import uuid

import jwt
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.exceptions import UnauthorizedError
from app.core.security import (
    Permission,
    Role,
    create_token,
    decode_token,
    has_permission,
    hash_password,
    verify_password,
)


def test_password_hash_roundtrip():
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong", hashed)


def test_token_roundtrip_carries_tenant(settings):
    tenant = str(uuid.uuid4())
    token = create_token(settings, subject=str(uuid.uuid4()), tenant_id=tenant, role=Role.ANALYST)
    claims = decode_token(settings, token)
    assert claims["tid"] == tenant and claims["role"] == "ANALYST"


def test_refresh_token_rejected_as_access(settings):
    token = create_token(
        settings, subject="u", tenant_id="t", role=Role.VIEWER, token_type="refresh"
    )
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
        (Role.VIEWER, Permission.QUERY_RUN, True),
        (Role.VIEWER, Permission.DOCUMENT_UPLOAD, False),
        (Role.ANALYST, Permission.DOCUMENT_DELETE, False),
        (Role.LEGAL_MANAGER, Permission.DOCUMENT_DELETE, True),
        (Role.LEGAL_MANAGER, Permission.USER_MANAGE, False),
        (Role.ADMIN, Permission.USER_MANAGE, True),
    ],
)
def test_rbac_matrix(role, permission, allowed):
    assert has_permission(role, permission) is allowed


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
