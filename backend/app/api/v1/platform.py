"""
Platform console API (Phase 18): /api/v1/platform/...

For the people who operate DocuNexa AI, not for organizations. Separate
sign-in and token audience; SUPPORT admins read, SUPER_ADMIN admins change.
No route here returns organization content (documents, chunks, questions,
answers) — only accounts, counts and settings.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.core.dependencies import (
    LoginThrottleDep,
    PlatformAdminDep,
    PlatformAuthServiceDep,
    PlatformServiceDep,
    RequestMetaDep,
    SuperAdminDep,
)
from app.core.exceptions import UnauthorizedError
from app.db.models import OrganizationStatus, Plan
from app.schemas.auth import LoginRequest, RefreshRequest, TokenPair
from app.schemas.common import ApiResponse, Page
from app.schemas.platform import (
    CreatePlatformAdminRequest,
    DeleteOrganizationRequest,
    OrganizationDetail,
    OrganizationSummary,
    PlanOut,
    PlatformAdminOut,
    PlatformAuditOut,
    PlatformOverview,
    UpdateMemberRequest,
    UpdateOrganizationRequest,
    UpdatePlatformAdminRequest,
)
from app.services.platform_service import PlatformService

router = APIRouter(prefix="/platform", tags=["platform"])


# --- Sign-in --------------------------------------------------------------------------


@router.post("/auth/login", summary="Platform admin sign-in", response_model=ApiResponse[TokenPair])
async def login(
    body: LoginRequest,
    service: PlatformAuthServiceDep,
    meta: RequestMetaDep,
    throttle: LoginThrottleDep,
) -> ApiResponse[TokenPair]:
    await throttle.check(body.email)
    try:
        tokens = await service.login(body, meta)
    except UnauthorizedError:
        await throttle.failed(body.email)
        raise
    await throttle.succeeded(body.email)
    return ApiResponse(data=tokens)


@router.post(
    "/auth/refresh", summary="Renew a platform session", response_model=ApiResponse[TokenPair]
)
async def refresh(body: RefreshRequest, service: PlatformAuthServiceDep) -> ApiResponse[TokenPair]:
    return ApiResponse(data=await service.refresh(body.refresh_token))


@router.post(
    "/auth/logout",
    summary="End a platform session",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def logout(body: RefreshRequest, service: PlatformAuthServiceDep) -> Response:
    await service.logout(body.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/me", summary="The signed-in platform admin", response_model=ApiResponse[PlatformAdminOut]
)
async def me(admin: PlatformAdminDep, service: PlatformServiceDep) -> ApiResponse[PlatformAdminOut]:
    admins = {a.id: a for a in await service.list_admins()}
    found = admins.get(admin.admin_id)
    if found is None or not found.is_active:
        raise UnauthorizedError()
    return ApiResponse(data=found)


# --- Overview and plans -------------------------------------------------------------------


@router.get("/overview", summary="Platform totals", response_model=ApiResponse[PlatformOverview])
async def overview(
    _: PlatformAdminDep, service: PlatformServiceDep
) -> ApiResponse[PlatformOverview]:
    return ApiResponse(data=await service.overview())


@router.get(
    "/plans", summary="Plans and their default limits", response_model=ApiResponse[list[PlanOut]]
)
async def plans(_: PlatformAdminDep) -> ApiResponse[list[PlanOut]]:
    return ApiResponse(data=PlatformService.plans())


# --- Organizations ----------------------------------------------------------------------


@router.get(
    "/organizations",
    summary="Every organization with its plan, limits and usage",
    response_model=ApiResponse[Page[OrganizationSummary]],
)
async def list_organizations(
    _: PlatformAdminDep,
    service: PlatformServiceDep,
    q: Annotated[
        str | None, Query(max_length=200, description="Name, slug or a member's email")
    ] = None,
    status_filter: Annotated[OrganizationStatus | None, Query(alias="status")] = None,
    plan: Annotated[Plan | None, Query()] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ApiResponse[Page[OrganizationSummary]]:
    return ApiResponse(
        data=await service.list_organizations(
            q=q, status=status_filter, plan=plan, offset=offset, limit=limit
        )
    )


@router.get(
    "/organizations/{org_id}",
    summary="One organization: usage, members and settings",
    response_model=ApiResponse[OrganizationDetail],
)
async def get_organization(
    _: PlatformAdminDep, org_id: uuid.UUID, service: PlatformServiceDep
) -> ApiResponse[OrganizationDetail]:
    return ApiResponse(data=await service.get_organization(org_id))


@router.patch(
    "/organizations/{org_id}",
    summary="Suspend or reactivate, change plan or limits",
    response_model=ApiResponse[OrganizationDetail],
)
async def update_organization(
    admin: SuperAdminDep,
    org_id: uuid.UUID,
    body: UpdateOrganizationRequest,
    service: PlatformServiceDep,
    meta: RequestMetaDep,
) -> ApiResponse[OrganizationDetail]:
    return ApiResponse(
        data=await service.update_organization(org_id, body, actor_id=admin.admin_id, meta=meta)
    )


@router.delete(
    "/organizations/{org_id}",
    summary="Delete an organization and erase all its data",
    status_code=status.HTTP_202_ACCEPTED,
    response_class=Response,
)
async def delete_organization(
    admin: SuperAdminDep,
    org_id: uuid.UUID,
    body: DeleteOrganizationRequest,
    service: PlatformServiceDep,
    meta: RequestMetaDep,
) -> Response:
    """Access ends immediately; vectors, files, caches and rows are erased in
    the background. Body: {"confirm_name": "<exact organization name>"}."""
    await service.delete_organization(
        org_id, confirm_name=body.confirm_name, actor_id=admin.admin_id, meta=meta
    )
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.patch(
    "/organizations/{org_id}/members/{user_id}",
    summary="Activate or deactivate one member (support)",
    response_model=ApiResponse[OrganizationDetail],
)
async def update_member(
    admin: SuperAdminDep,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    body: UpdateMemberRequest,
    service: PlatformServiceDep,
    meta: RequestMetaDep,
) -> ApiResponse[OrganizationDetail]:
    return ApiResponse(
        data=await service.set_member_active(
            org_id, user_id, body.is_active, actor_id=admin.admin_id, meta=meta
        )
    )


# --- Platform admins --------------------------------------------------------------------


@router.get(
    "/admins", summary="Platform admins", response_model=ApiResponse[list[PlatformAdminOut]]
)
async def list_admins(
    _: SuperAdminDep, service: PlatformServiceDep
) -> ApiResponse[list[PlatformAdminOut]]:
    return ApiResponse(data=await service.list_admins())


@router.post(
    "/admins",
    summary="Add a platform admin",
    response_model=ApiResponse[PlatformAdminOut],
    status_code=status.HTTP_201_CREATED,
)
async def create_admin(
    admin: SuperAdminDep,
    body: CreatePlatformAdminRequest,
    service: PlatformServiceDep,
    meta: RequestMetaDep,
) -> ApiResponse[PlatformAdminOut]:
    return ApiResponse(data=await service.create_admin(body, actor_id=admin.admin_id, meta=meta))


@router.patch(
    "/admins/{admin_id}",
    summary="Change a platform admin's role or status",
    response_model=ApiResponse[PlatformAdminOut],
)
async def update_admin(
    admin: SuperAdminDep,
    admin_id: uuid.UUID,
    body: UpdatePlatformAdminRequest,
    service: PlatformServiceDep,
    meta: RequestMetaDep,
) -> ApiResponse[PlatformAdminOut]:
    return ApiResponse(
        data=await service.update_admin(admin_id, body, actor_id=admin.admin_id, meta=meta)
    )


# --- Audit ------------------------------------------------------------------------------


@router.get(
    "/audit",
    summary="What platform admins did",
    response_model=ApiResponse[Page[PlatformAuditOut]],
)
async def audit(
    _: PlatformAdminDep,
    service: PlatformServiceDep,
    organization_id: Annotated[uuid.UUID | None, Query()] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ApiResponse[Page[PlatformAuditOut]]:
    return ApiResponse(
        data=await service.audit(organization_id=organization_id, offset=offset, limit=limit)
    )
