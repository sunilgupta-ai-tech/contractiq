"""
Roles and permissions within an organization (Phase 17).

Listing roles needs user management (to assign them) or role management;
creating, editing and deleting custom roles needs role management. The
permission catalog is readable by any signed-in user (the UI uses it).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status

from app.core.dependencies import (
    CurrentUserDep,
    RequestMetaDep,
    RoleManagerDep,
    RoleServiceDep,
)
from app.core.exceptions import ForbiddenError
from app.core.security import Permission
from app.schemas.common import ApiResponse
from app.schemas.user import (
    CreateRoleRequest,
    PermissionOut,
    RoleOut,
    UpdateRoleRequest,
)

router = APIRouter(tags=["roles"])


@router.get(
    "/permissions",
    summary="The permission catalog custom roles are built from",
    response_model=ApiResponse[list[PermissionOut]],
)
async def list_permissions(_: CurrentUserDep) -> ApiResponse[list[PermissionOut]]:
    return ApiResponse(data=PermissionOut.catalog())


@router.get(
    "/roles",
    summary="System roles plus the organization's custom roles",
    response_model=ApiResponse[list[RoleOut]],
)
async def list_roles(user: CurrentUserDep, service: RoleServiceDep) -> ApiResponse[list[RoleOut]]:
    if not (user.can(Permission.USER_MANAGE) or user.can(Permission.ROLE_MANAGE)):
        raise ForbiddenError()
    return ApiResponse(data=await service.list())


@router.post(
    "/roles",
    summary="Create a custom role",
    response_model=ApiResponse[RoleOut],
    status_code=status.HTTP_201_CREATED,
)
async def create_role(
    user: RoleManagerDep, body: CreateRoleRequest, service: RoleServiceDep, meta: RequestMetaDep
) -> ApiResponse[RoleOut]:
    return ApiResponse(
        data=await service.create(
            body, actor_id=user.user_id, actor_permissions=user.permissions, meta=meta
        )
    )


@router.patch(
    "/roles/{role_id}",
    summary="Rename a custom role or change its permissions",
    response_model=ApiResponse[RoleOut],
)
async def update_role(
    user: RoleManagerDep,
    role_id: uuid.UUID,
    body: UpdateRoleRequest,
    service: RoleServiceDep,
    meta: RequestMetaDep,
) -> ApiResponse[RoleOut]:
    return ApiResponse(
        data=await service.update(
            role_id,
            body,
            actor_id=user.user_id,
            actor_role_id=user.role_id,
            actor_permissions=user.permissions,
            meta=meta,
        )
    )


@router.delete(
    "/roles/{role_id}",
    summary="Delete a custom role that no user has",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_role(
    user: RoleManagerDep, role_id: uuid.UUID, service: RoleServiceDep, meta: RequestMetaDep
) -> Response:
    await service.delete(role_id, actor_id=user.user_id, actor_role_id=user.role_id, meta=meta)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
