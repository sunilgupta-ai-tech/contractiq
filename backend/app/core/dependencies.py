"""
FastAPI dependency providers.

Route handlers receive infrastructure and services through `Depends`, never
by importing globals. Tests swap any of these via `app.dependency_overrides`.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.logging import tenant_id_ctx
from app.core.resources import Resources
from app.core.security import Permission, Role, decode_token, has_permission
from app.services.health_service import HealthService

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
    """Authenticated principal. `tenant_id` comes from the signed token —
    never from a request parameter the client controls."""

    user_id: uuid.UUID
    tenant_id: uuid.UUID
    role: Role


async def get_current_user(
    settings: Annotated[Settings, Depends(get_settings)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> CurrentUser:
    if credentials is None:
        raise UnauthorizedError()
    claims = decode_token(settings, credentials.credentials)
    user = CurrentUser(
        user_id=uuid.UUID(claims["sub"]),
        tenant_id=uuid.UUID(claims["tid"]),
        role=Role(claims["role"]),
    )
    tenant_id_ctx.set(str(user.tenant_id))
    return user


def require_permission(permission: Permission) -> Callable[..., CurrentUser]:
    """Route-level RBAC: `Depends(require_permission(Permission.DOCUMENT_UPLOAD))`."""

    def _checker(user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
        if not has_permission(user.role, permission):
            raise ForbiddenError()
        return user

    return _checker


SettingsDep = Annotated[Settings, Depends(get_settings)]
DbSession = Annotated[AsyncSession, Depends(get_db_session)]
CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
