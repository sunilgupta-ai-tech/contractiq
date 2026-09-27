"""
Invitations (Phase 22): an admin invites a person by email with a role; the
person opens the link, sets their own password and is signed in.

* The link carries a 256-bit random token; only its SHA-256 is stored.
* Links work once and expire (INVITATION_TTL_DAYS, default 7).
* The same rules as adding a user directly: email unique platform-wide,
  role within the inviter's own access, plan user limit (checked again on
  acceptance, when the seat is actually taken).
* No email is sent by the API yet: the admin shares the link. Wiring an
  email provider later only changes where the link goes.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.core.security import Permission, hash_password
from app.db.models import Invitation, Organization, Role, User
from app.db.repositories.role_repository import RoleRepository
from app.db.repositories.user_repository import find_user_by_email
from app.schemas.invitation import (
    AcceptInvitationRequest,
    CreateInvitationRequest,
    InvitationCreated,
    InvitationOut,
    InvitationPreview,
)
from app.services.audit_service import RequestMeta, record_audit
from app.services.auth_service import EMAIL_TAKEN
from app.services.plans import ensure_can_add_user
from app.services.user_service import check_within

INVALID_LINK = "This invitation link is invalid or has expired. Ask for a new one."


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _out(invitation: Invitation, role_name: str) -> InvitationOut:
    return InvitationOut(
        id=invitation.id,
        email=invitation.email,
        role_id=invitation.role_id,
        role_name=role_name,
        expires_at=invitation.expires_at,
        created_at=invitation.created_at,
    )


class InvitationService:
    """Tenant side: create, list and revoke invitations."""

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID, *, ttl_days: int = 7) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.ttl = timedelta(days=ttl_days)

    async def create(
        self,
        data: CreateInvitationRequest,
        *,
        actor_id: uuid.UUID,
        actor_permissions: frozenset[Permission],
        meta: RequestMeta,
    ) -> InvitationCreated:
        role = await RoleRepository(self.session, self.tenant_id).get(data.role_id)
        check_within(role, actor_permissions)
        if await find_user_by_email(self.session, data.email):
            raise ConflictError(EMAIL_TAKEN)
        await ensure_can_add_user(self.session, self.tenant_id)
        token = secrets.token_urlsafe(32)
        invitation = Invitation(
            organization_id=self.tenant_id,
            email=data.email,
            role_id=role.id,
            token_hash=token_hash(token),
            invited_by_id=actor_id,
            expires_at=datetime.now(UTC) + self.ttl,
        )
        self.session.add(invitation)
        await self.session.flush()
        record_audit(
            self.session,
            tenant_id=self.tenant_id,
            actor_user_id=actor_id,
            action="invitation.create",
            resource_type="invitation",
            resource_id=invitation.id,
            meta=meta,
            metadata={"role": role.name},
        )
        await self.session.commit()
        await self.session.refresh(invitation)
        return InvitationCreated(**_out(invitation, role.name).model_dump(), token=token)

    async def pending(self) -> list[InvitationOut]:
        now = datetime.now(UTC)
        rows = (
            await self.session.execute(
                select(Invitation, Role.name)
                .join(Role, Role.id == Invitation.role_id)
                .where(
                    Invitation.organization_id == self.tenant_id,
                    Invitation.accepted_at.is_(None),
                    Invitation.revoked_at.is_(None),
                    Invitation.expires_at > now,
                )
                .order_by(Invitation.created_at.desc())
            )
        ).all()
        return [_out(invitation, role_name) for invitation, role_name in rows]

    async def revoke(
        self, invitation_id: uuid.UUID, *, actor_id: uuid.UUID, meta: RequestMeta
    ) -> None:
        invitation = (
            await self.session.execute(
                select(Invitation).where(
                    Invitation.id == invitation_id, Invitation.organization_id == self.tenant_id
                )
            )
        ).scalar_one_or_none()
        if invitation is None:
            raise NotFoundError("Invitation not found.")
        invitation.revoked_at = datetime.now(UTC)
        record_audit(
            self.session,
            tenant_id=self.tenant_id,
            actor_user_id=actor_id,
            action="invitation.revoke",
            resource_type="invitation",
            resource_id=invitation.id,
            meta=meta,
        )
        await self.session.commit()


# --- Public side: the invitee has no account (and no tenant) yet ------------------------


async def _valid(session: AsyncSession, token: str) -> tuple[Invitation, Organization, Role]:
    row = (
        await session.execute(
            select(Invitation, Organization, Role)
            .join(Organization, Organization.id == Invitation.organization_id)
            .join(Role, Role.id == Invitation.role_id)
            .where(Invitation.token_hash == token_hash(token))
        )
    ).first()
    if row is None:
        raise NotFoundError(INVALID_LINK)
    invitation, org, role = row
    if (
        invitation.accepted_at is not None
        or invitation.revoked_at is not None
        or invitation.expires_at <= datetime.now(UTC)
        or not org.is_active
    ):
        raise NotFoundError(INVALID_LINK)
    return invitation, org, role


async def preview(session: AsyncSession, token: str) -> InvitationPreview:
    invitation, org, role = await _valid(session, token)
    return InvitationPreview(
        email=invitation.email,
        organization_name=org.name,
        role_name=role.name,
        expires_at=invitation.expires_at,
    )


async def accept(
    session: AsyncSession, token: str, data: AcceptInvitationRequest, meta: RequestMeta
) -> User:
    """Create the account and mark the link used. Returns the new user (the
    caller issues tokens)."""
    invitation, org, role = await _valid(session, token)
    if await find_user_by_email(session, invitation.email):
        raise ConflictError(EMAIL_TAKEN)
    await ensure_can_add_user(session, org.id)
    user = User(
        organization_id=org.id,
        email=invitation.email,
        full_name=data.full_name,
        password_hash=hash_password(data.password),
        role_id=role.id,
        last_login_at=datetime.now(UTC),
    )
    session.add(user)
    invitation.accepted_at = datetime.now(UTC)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictError(EMAIL_TAKEN) from exc
    record_audit(
        session,
        tenant_id=org.id,
        actor_user_id=user.id,
        action="invitation.accept",
        resource_type="invitation",
        resource_id=invitation.id,
        meta=meta,
    )
    await session.commit()
    await session.refresh(user, ["role"])
    return user
