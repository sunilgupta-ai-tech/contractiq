"""
FastAPI dependency providers.

Route handlers receive infrastructure and services through `Depends`, never
by importing globals. Tests swap any of these via `app.dependency_overrides`.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.logging import tenant_id_ctx
from app.core.resources import Resources
from app.core.security import Permission, decode_token, parse_permissions
from app.core.sessions import token_is_current
from app.db.tenancy import bind_tenant
from app.guardrails.input_guardrails import (
    RateLimiter,
    limits_for,
    login_limits,
    subject_hash,
)
from app.services.audit_service import RequestMeta
from app.services.auth_service import AuthService
from app.services.comparison_service import ComparisonService
from app.services.contract_service import ContractService
from app.services.document_service import DocumentService
from app.services.health_service import HealthService
from app.services.query_service import QueryService
from app.services.risk_service import RiskService
from app.services.role_service import RoleService
from app.services.user_service import UserService

_bearer = HTTPBearer(auto_error=False)


def get_resources(request: Request) -> Resources:
    return request.app.state.resources  # type: ignore[no-any-return]


async def get_db_session(
    resources: Annotated[Resources, Depends(get_resources)],
) -> AsyncIterator[AsyncSession]:
    async for session in resources.db.session():
        yield session


def get_health_service(
    resources: Annotated[Resources, Depends(get_resources)],
) -> HealthService:
    return HealthService.from_resources(resources)


@dataclass(frozen=True)
class CurrentUser:
    """Authenticated principal. `tenant_id` and `permissions` come from the
    signed token — never from a request parameter the client controls."""

    user_id: uuid.UUID
    tenant_id: uuid.UUID
    role: str  # the role's name, for logs and display
    role_id: uuid.UUID
    permissions: frozenset[Permission]

    def can(self, permission: Permission) -> bool:
        return permission in self.permissions


STALE_SESSION = "Your access has changed. Please sign in again."


async def get_current_user(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> CurrentUser:
    if credentials is None:
        raise UnauthorizedError()
    claims = decode_token(settings, credentials.credentials)
    try:
        user = CurrentUser(
            user_id=uuid.UUID(claims["sub"]),
            tenant_id=uuid.UUID(claims["tid"]),
            role=str(claims["role"]),
            role_id=uuid.UUID(claims["rid"]),
            permissions=parse_permissions(claims["perms"]),
        )
    except (ValueError, TypeError) as exc:
        raise UnauthorizedError("Invalid or expired token.") from exc
    # A role change, deactivation or suspension since the token was issued
    # makes it stale (app/core/sessions.py); the client refreshes.
    resources: Resources | None = getattr(request.app.state, "resources", None)
    if resources is not None and not await token_is_current(
        resources.redis, user_id=claims["sub"], tenant_id=claims["tid"], ts=int(claims["ts"])
    ):
        raise UnauthorizedError(STALE_SESSION)
    tenant_id_ctx.set(str(user.tenant_id))
    return user


async def get_tenant_session(
    user: Annotated[CurrentUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AsyncSession:
    """The request's session, bound to the caller's tenant (Phase 15): from
    here on PostgreSQL row-level security only lets it reach that tenant's
    rows, whatever the query. FastAPI caches `get_db_session` per request, so
    every dependency of the request shares this one bound session."""
    await bind_tenant(session, user.tenant_id)
    return session


def require_permission(permission: Permission) -> Callable[..., CurrentUser]:
    """Route-level RBAC: `Depends(require_permission(Permission.DOCUMENT_UPLOAD))`."""

    def _checker(user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
        if not user.can(permission):
            raise ForbiddenError()
        return user

    return _checker


def get_rate_limiter(request: Request) -> RateLimiter:
    """Redis-backed limiter; disabled when the app runs without infrastructure
    (unit tests that don't start the lifespan)."""
    resources: Resources | None = getattr(request.app.state, "resources", None)
    if resources is None:
        return RateLimiter(None)
    return RateLimiter(resources.redis, enabled=resources.settings.rate_limit_enabled)


def rate_limit(kind: str) -> Callable[..., Awaitable[None]]:
    """Per-user (and per-tenant) request limits for costly endpoints (Phase 11).
    Declare it *after* the permission dependency, so a request that will be
    refused anyway does not use up the caller's allowance."""

    async def _check(
        request: Request,
        user: Annotated[CurrentUser, Depends(get_current_user)],
        limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    ) -> None:
        resources: Resources | None = getattr(request.app.state, "resources", None)
        if resources is None or not limiter.enabled:
            return
        for limit, per_tenant in limits_for(kind, settings=resources.settings):
            subject = "tenant" if per_tenant else str(user.user_id)
            await limiter.hit(limit, subject, tenant_id=str(user.tenant_id))

    return _check


@dataclass
class LoginThrottle:
    """Failed-login limits per (IP, email) and per IP (Phase 11). Only failures
    count, so a user who signs in correctly is never slowed down."""

    limiter: RateLimiter
    settings: Settings
    ip: str

    async def check(self, email: str) -> None:
        pair, per_ip = login_limits(self.settings)
        await self.limiter.check(pair, subject_hash(self.ip, email))
        await self.limiter.check(per_ip, subject_hash(self.ip))

    async def failed(self, email: str) -> None:
        pair, per_ip = login_limits(self.settings)
        await self.limiter.record(pair, subject_hash(self.ip, email))
        await self.limiter.record(per_ip, subject_hash(self.ip))

    async def succeeded(self, email: str) -> None:
        pair, _ = login_limits(self.settings)
        await self.limiter.reset(pair, subject_hash(self.ip, email))


def get_login_throttle(
    request: Request,
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> LoginThrottle:
    resources: Resources | None = getattr(request.app.state, "resources", None)
    ip = request.client.host if request.client else "unknown"
    return LoginThrottle(limiter, resources.settings if resources else settings, ip)


def get_request_meta(request: Request) -> RequestMeta:
    return RequestMeta.from_client_host(request.client.host if request.client else None)


def get_auth_service(
    resources: Annotated[Resources, Depends(get_resources)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthService:
    # Same `get_settings` as `get_current_user`, so tokens are signed and
    # verified with the same key.
    return AuthService(session, resources.redis, settings)


def _revoke_ttl_s(request: Request) -> int:
    resources: Resources | None = getattr(request.app.state, "resources", None)
    settings = resources.settings if resources else get_settings()
    return settings.access_token_expire_minutes * 60


def get_user_service(
    request: Request,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
) -> UserService:
    """Scoped to the caller's tenant from the signed token."""
    resources: Resources | None = getattr(request.app.state, "resources", None)
    return UserService(
        session,
        user.tenant_id,
        redis=resources.redis if resources else None,
        revoke_ttl_s=_revoke_ttl_s(request),
    )


def get_role_service(
    request: Request,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
) -> RoleService:
    """Custom roles (Phase 17), scoped to the caller's tenant."""
    resources: Resources | None = getattr(request.app.state, "resources", None)
    return RoleService(
        session,
        user.tenant_id,
        redis=resources.redis if resources else None,
        revoke_ttl_s=_revoke_ttl_s(request),
    )


def get_document_service(
    user: Annotated[CurrentUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    resources: Annotated[Resources, Depends(get_resources)],
) -> DocumentService:
    """Scoped to the caller's tenant from the signed token."""
    return DocumentService(session, user.tenant_id, resources)


def get_query_service(
    user: Annotated[CurrentUser, Depends(require_permission(Permission.QUERY_RUN))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    resources: Annotated[Resources, Depends(get_resources)],
) -> QueryService:
    """Scoped to the caller's tenant and user (from the signed token)."""
    return QueryService(
        session,
        tenant_id=user.tenant_id,
        user_id=user.user_id,
        permissions=user.permissions,
        resources=resources,
    )


def get_contract_service(
    user: Annotated[CurrentUser, Depends(require_permission(Permission.ANALYSIS_RUN))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    resources: Annotated[Resources, Depends(get_resources)],
) -> ContractService:
    """Contract analysis (Phase 10), scoped to the caller's tenant."""
    return ContractService(session, user.tenant_id, resources)


def get_risk_service(
    contracts: Annotated[ContractService, Depends(get_contract_service)],
) -> RiskService:
    return RiskService(contracts)


def get_comparison_service(
    contracts: Annotated[ContractService, Depends(get_contract_service)],
) -> ComparisonService:
    return ComparisonService(contracts)


SettingsDep = Annotated[Settings, Depends(get_settings)]
DbSession = Annotated[AsyncSession, Depends(get_db_session)]
TenantSession = Annotated[AsyncSession, Depends(get_tenant_session)]
CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
RequestMetaDep = Annotated[RequestMeta, Depends(get_request_meta)]
AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
UserServiceDep = Annotated[UserService, Depends(get_user_service)]
UserManagerDep = Annotated[CurrentUser, Depends(require_permission(Permission.USER_MANAGE))]
RoleManagerDep = Annotated[CurrentUser, Depends(require_permission(Permission.ROLE_MANAGE))]
RoleServiceDep = Annotated[RoleService, Depends(get_role_service)]
DocumentServiceDep = Annotated[DocumentService, Depends(get_document_service)]
DocumentReaderDep = Annotated[CurrentUser, Depends(require_permission(Permission.DOCUMENT_READ))]
DocumentUploaderDep = Annotated[
    CurrentUser, Depends(require_permission(Permission.DOCUMENT_UPLOAD))
]
DocumentDeleterDep = Annotated[CurrentUser, Depends(require_permission(Permission.DOCUMENT_DELETE))]
QueryRunnerDep = Annotated[CurrentUser, Depends(require_permission(Permission.QUERY_RUN))]
QueryServiceDep = Annotated[QueryService, Depends(get_query_service)]
AnalystDep = Annotated[CurrentUser, Depends(require_permission(Permission.ANALYSIS_RUN))]
ContractServiceDep = Annotated[ContractService, Depends(get_contract_service)]
RiskServiceDep = Annotated[RiskService, Depends(get_risk_service)]
ComparisonServiceDep = Annotated[ComparisonService, Depends(get_comparison_service)]
QueryRateLimitDep = Annotated[None, Depends(rate_limit("query"))]
AnalysisRateLimitDep = Annotated[None, Depends(rate_limit("analysis"))]
UploadRateLimitDep = Annotated[None, Depends(rate_limit("upload"))]
LoginThrottleDep = Annotated[LoginThrottle, Depends(get_login_throttle)]
