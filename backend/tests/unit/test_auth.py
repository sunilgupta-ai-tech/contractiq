import uuid
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core.dependencies import get_auth_service
from app.core.exceptions import ForbiddenError, ServiceUnavailableError, UnauthorizedError
from app.core.security import Role, create_token
from app.schemas.auth import LoginRequest, RegisterRequest, TokenPair
from app.schemas.user import UpdateUserRequest
from app.services.audit_service import RequestMeta
from app.services.auth_service import claim_refresh_token, slugify
from app.services.user_service import UserService


def _register(**overrides):
    data = {
        "organization_name": "Acme Legal",
        "full_name": "Ada Admin",
        "email": "ada@acme.test",
        "password": "correct horse battery",
    } | overrides
    return RegisterRequest(**data)


# --- Schemas ---------------------------------------------------------------------


def test_email_is_normalized():
    assert _register(email="  Ada@ACME.test ").email == "ada@acme.test"


@pytest.mark.parametrize("email", ["not-an-email", "a@b", "a b@c.com", "@acme.test"])
def test_invalid_email_rejected(email):
    with pytest.raises(ValidationError):
        _register(email=email)


def test_short_password_rejected():
    with pytest.raises(ValidationError, match="at least 12"):
        _register(password="short")


def test_password_over_bcrypt_limit_rejected_not_truncated():
    # 37 characters but 74 bytes: bcrypt would silently ignore the tail.
    with pytest.raises(ValidationError, match="72 bytes"):
        _register(password="é" * 37)


def test_login_does_not_enforce_new_password_policy():
    # Existing passwords that predate a policy change must still work.
    assert LoginRequest(email="a@b.co", password="old").password == "old"


def test_slug_is_url_safe_and_unique():
    a, b = slugify("Acme & Sons, Ltd."), slugify("Acme & Sons, Ltd.")
    assert a.startswith("acme-sons-ltd-") and a != b
    assert slugify("!!!").startswith("org-")


@pytest.mark.parametrize(
    ("host", "expected"),
    [("127.0.0.1", "127.0.0.1"), ("::1", "::1"), ("testclient", None), (None, None)],
)
def test_request_meta_keeps_only_valid_ips(host, expected):
    assert RequestMeta.from_client_host(host).ip_address == expected


# --- Refresh-token replay protection ---------------------------------------------


class FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True


async def test_refresh_token_can_be_claimed_once():
    redis = FakeRedis()
    assert await claim_refresh_token(redis, "jti-1", 9_999_999_999) is True
    assert await claim_refresh_token(redis, "jti-1", 9_999_999_999) is False
    assert await claim_refresh_token(redis, "jti-2", 9_999_999_999) is True


async def test_refresh_fails_closed_when_redis_is_down():
    redis = MagicMock()

    async def boom(*_, **__):
        raise RedisConnectionError("down")

    redis.set = boom
    with pytest.raises(ServiceUnavailableError):
        await claim_refresh_token(redis, "jti", 9_999_999_999)


# --- Users service rules that apply before any database access -------------------


async def test_admin_cannot_change_own_role_or_status():
    me = uuid.uuid4()
    service = UserService(MagicMock(), uuid.uuid4())
    for change in ({"role": Role.VIEWER}, {"is_active": False}):
        with pytest.raises(ForbiddenError):
            await service.update(me, UpdateUserRequest(**change), actor_id=me, meta=RequestMeta())


# --- Routes ----------------------------------------------------------------------


def _token(settings, role=Role.VIEWER, token_type="access"):  # noqa: S107
    return create_token(
        settings,
        subject=str(uuid.uuid4()),
        tenant_id=str(uuid.uuid4()),
        role=role,
        token_type=token_type,
    )


@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", "/api/v1/users/me"), ("GET", "/api/v1/users"), ("POST", "/api/v1/users")],
)
async def test_user_routes_require_a_token(client, method, path):
    response = await client.request(method, path)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_refresh_token_is_not_accepted_as_bearer(client, settings):
    token = _token(settings, role=Role.ADMIN, token_type="refresh")
    response = await client.get("/api/v1/users", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


@pytest.mark.parametrize("role", [Role.VIEWER, Role.ANALYST, Role.LEGAL_MANAGER])
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/users"),
        ("POST", "/api/v1/users"),
        ("PATCH", f"/api/v1/users/{uuid.uuid4()}"),
    ],
)
async def test_only_admins_manage_users(client, settings, role, method, path):
    # Rejected before the request body is read or a DB session is opened.
    headers = {"Authorization": f"Bearer {_token(settings, role=role)}"}
    response = await client.request(method, path, headers=headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


class FakeAuthService:
    pair = TokenPair(access_token="a", refresh_token="r", expires_in=1800)

    async def register(self, data, meta):
        return self.pair

    async def login(self, data, meta):
        if data.password != "right-password":
            raise UnauthorizedError("Invalid email or password.")
        return self.pair

    async def refresh(self, token):
        return self.pair


@pytest.fixture
def fake_auth(app):
    app.dependency_overrides[get_auth_service] = FakeAuthService


async def test_register_returns_201_with_tokens(client, fake_auth):
    response = await client.post("/api/v1/auth/register", json=_register().model_dump())
    assert response.status_code == 201
    assert response.json()["data"]["token_type"] == "bearer"


async def test_login_success_and_failure_envelopes(client, fake_auth):
    ok = await client.post(
        "/api/v1/auth/login", json={"email": "a@b.co", "password": "right-password"}
    )
    assert ok.status_code == 200 and ok.json()["data"]["access_token"] == "a"

    bad = await client.post("/api/v1/auth/login", json={"email": "a@b.co", "password": "nope"})
    assert bad.status_code == 401
    assert bad.json()["error"]["message"] == "Invalid email or password."


async def test_register_validation_errors_do_not_echo_password(client, fake_auth):
    body = _register().model_dump() | {"password": "tiny-secret"}
    response = await client.post("/api/v1/auth/register", json=body)
    assert response.status_code == 422
    assert "tiny-secret" not in response.text
