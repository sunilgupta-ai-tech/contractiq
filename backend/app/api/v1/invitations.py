"""
Invitations (Phase 22).

Admins (user:manage) create, list and revoke them; the invitee — who has no
account yet — previews and accepts with the link's token, then is signed in.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status

from app.core.dependencies import (
    AuthServiceDep,
    DbSession,
    LoginThrottleDep,
    RequestMetaDep,
    SettingsDep,
    TenantSession,
    UserManagerDep,
)
from app.core.exceptions import NotFoundError
from app.schemas.auth import TokenPair
from app.schemas.common import ApiResponse
from app.schemas.invitation import (
    AcceptInvitationRequest,
    CreateInvitationRequest,
    InvitationCreated,
    InvitationOut,
    InvitationPreview,
)
from app.services import invitation_service
from app.services.invitation_service import InvitationService

router = APIRouter(tags=["invitations"])


@router.post(
    "/invitations",
    summary="Invite a person to the organization",
    response_model=ApiResponse[InvitationCreated],
    status_code=status.HTTP_201_CREATED,
)
async def create_invitation(
    admin: UserManagerDep,
    body: CreateInvitationRequest,
    session: TenantSession,
    settings: SettingsDep,
    meta: RequestMetaDep,
) -> ApiResponse[InvitationCreated]:
    """The response carries the link token once; build the link as
    `<app>/invite/<token>` and share it with the person."""
    service = InvitationService(session, admin.tenant_id, ttl_days=settings.invitation_ttl_days)
    return ApiResponse(
        data=await service.create(
            body, actor_id=admin.user_id, actor_permissions=admin.permissions, meta=meta
        )
    )


@router.get(
    "/invitations",
    summary="Pending invitations",
    response_model=ApiResponse[list[InvitationOut]],
)
async def list_invitations(
    admin: UserManagerDep, session: TenantSession
) -> ApiResponse[list[InvitationOut]]:
    return ApiResponse(data=await InvitationService(session, admin.tenant_id).pending())


@router.delete(
    "/invitations/{invitation_id}",
    summary="Revoke an invitation",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def revoke_invitation(
    admin: UserManagerDep, invitation_id: uuid.UUID, session: TenantSession, meta: RequestMetaDep
) -> Response:
    await InvitationService(session, admin.tenant_id).revoke(
        invitation_id, actor_id=admin.user_id, meta=meta
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/auth/invitations/{token}",
    summary="What an invitation link is for (no sign-in needed)",
    response_model=ApiResponse[InvitationPreview],
)
async def preview_invitation(token: str, session: DbSession) -> ApiResponse[InvitationPreview]:
    return ApiResponse(data=await invitation_service.preview(session, token))


@router.post(
    "/auth/invitations/{token}/accept",
    summary="Accept an invitation: set a password and sign in",
    response_model=ApiResponse[TokenPair],
    status_code=status.HTTP_201_CREATED,
)
async def accept_invitation(
    token: str,
    body: AcceptInvitationRequest,
    session: DbSession,
    auth: AuthServiceDep,
    throttle: LoginThrottleDep,
    meta: RequestMetaDep,
) -> ApiResponse[TokenPair]:
    # Guessing tokens is throttled like guessing passwords (per IP).
    await throttle.check("invitation")
    try:
        user = await invitation_service.accept(session, token, body, meta)
    except NotFoundError:
        await throttle.failed("invitation")
        raise
    return ApiResponse(data=auth.issue_tokens(user))
