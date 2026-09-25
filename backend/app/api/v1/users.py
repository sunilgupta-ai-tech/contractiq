"""
User management within an organization.

Every route resolves the caller first (the RBAC dependency is declared
before the service), so unauthenticated or unauthorized requests are
rejected before a database session is opened.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.core.dependencies import CurrentUserDep, RequestMetaDep, UserManagerDep, UserServiceDep
from app.schemas.common import ApiResponse, Page
from app.schemas.user import CreateUserRequest, UpdateUserRequest, UserOut

router = APIRouter(tags=["users"])


@router.get("/users/me", summary="Current user profile", response_model=ApiResponse[UserOut])
async def get_me(user: CurrentUserDep, service: UserServiceDep) -> ApiResponse[UserOut]:
    return ApiResponse(data=await service.get(user.user_id))


@router.get(
    "/users",
    summary="List users in the caller's organization",
    response_model=ApiResponse[Page[UserOut]],
)
async def list_users(
    _: UserManagerDep,
    service: UserServiceDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ApiResponse[Page[UserOut]]:
    return ApiResponse(data=await service.list(offset=offset, limit=limit))


@router.post(
    "/users",
    summary="Add a user to the caller's organization",
    response_model=ApiResponse[UserOut],
    status_code=status.HTTP_201_CREATED,
)
async def create_user(
    admin: UserManagerDep, body: CreateUserRequest, service: UserServiceDep, meta: RequestMetaDep
) -> ApiResponse[UserOut]:
    return ApiResponse(data=await service.create(body, actor_id=admin.user_id, meta=meta))


@router.patch(
    "/users/{user_id}",
    summary="Change a user's name, role or active status",
    response_model=ApiResponse[UserOut],
)
async def update_user(
    admin: UserManagerDep,
    user_id: uuid.UUID,
    body: UpdateUserRequest,
    service: UserServiceDep,
    meta: RequestMetaDep,
) -> ApiResponse[UserOut]:
    return ApiResponse(data=await service.update(user_id, body, actor_id=admin.user_id, meta=meta))
