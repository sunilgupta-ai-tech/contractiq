"""Organization usage against its plan (Phase 22): for administrators."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.dependencies import TenantSession, UserManagerDep
from app.schemas.common import ApiResponse
from app.schemas.usage import OrgUsageOut
from app.services.usage import organization_usage

router = APIRouter(tags=["usage"])


@router.get(
    "/usage",
    summary="Storage, documents, users and AI usage against the plan",
    response_model=ApiResponse[OrgUsageOut],
)
async def get_usage(admin: UserManagerDep, session: TenantSession) -> ApiResponse[OrgUsageOut]:
    return ApiResponse(data=await organization_usage(session, admin.tenant_id))
