"""
User management within one organization.

The service is constructed with the caller's tenant ID (from the signed
token) and every read and write goes through a tenant-scoped repository, so
an ADMIN of one organization cannot see or change users of another — a
foreign user ID is reported as not found.
"""

from __future__ import annotations

import uuid

from redis.asyncio import Redis
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, ForbiddenError
from app.core.security import Permission, SystemRole, hash_password
from app.core.sessions import revoke_user_sessions
from app.db.models import SYSTEM_ROLE_IDS, Organization, Role, User
from app.db.repositories.role_repository import RoleRepository
from app.db.repositories.user_repository import UserRepository, find_user_by_email
from app.schemas.common import Page
from app.schemas.user import CreateUserRequest, MeOut, UpdateUserRequest, UserOut
from app.services.audit_service import RequestMeta, record_audit
from app.services.auth_service import EMAIL_TAKEN

BEYOND_OWN = "You cannot give a role more access than your own."


def check_within(role: Role, actor_permissions: frozenset[Permission]) -> None:
    """No privilege escalation: a user may only hand out (or change) access
    they hold themselves. An Admin holds every permission, so this only
    limits custom roles that were given user or role management."""
    if not role.permissions <= actor_permissions:
        raise ForbiddenError(BEYOND_OWN)


class UserService:
    def __init__(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        redis: Redis | None = None,
        revoke_ttl_s: int = 3600,
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.redis = redis
        self.revoke_ttl_s = revoke_ttl_s
        self.users = UserRepository(session, tenant_id)
        self.roles = RoleRepository(session, tenant_id)

    async def get(self, user_id: uuid.UUID) -> UserOut:
        return UserOut.of(await self.users.get(user_id))

    async def me(self, user_id: uuid.UUID) -> MeOut:
        """The caller's profile with their organization's name and size, and
        their role's current permissions."""
        user = await self.users.get(user_id)
        organization = await self.session.get(Organization, self.tenant_id)
        return MeOut(
            **UserOut.of(user).model_dump(),
            organization_name=organization.name if organization else "",
            member_count=await self.users.count(is_active=True),
            permissions=sorted(user.role.permissions),
        )

    async def list(self, *, offset: int, limit: int) -> Page[UserOut]:
        rows = await self.users.list(offset=offset, limit=limit)
        return Page(
            items=[UserOut.of(u) for u in rows],
            total=await self.users.count(),
            offset=offset,
            limit=limit,
        )

    async def create(
        self,
        data: CreateUserRequest,
        *,
        actor_id: uuid.UUID,
        actor_permissions: frozenset[Permission],
        meta: RequestMeta,
    ) -> UserOut:
        role = await self.roles.get(data.role_id or SYSTEM_ROLE_IDS[SystemRole.VIEWER])
        check_within(role, actor_permissions)
        # Emails are unique platform-wide, so this check is deliberately not
        # tenant-scoped. It reveals only that the address is taken.
        if await find_user_by_email(self.session, data.email):
            raise ConflictError(EMAIL_TAKEN)
        try:
            user = await self.users.add(
                User(
                    email=data.email,
                    full_name=data.full_name,
                    password_hash=hash_password(data.password),
                    role_id=role.id,
                    is_active=True,
                )
            )
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(EMAIL_TAKEN) from exc
        record_audit(
            self.session,
            tenant_id=self.tenant_id,
            actor_user_id=actor_id,
            action="user.create",
            resource_type="user",
            resource_id=user.id,
            meta=meta,
            metadata={"role_id": str(role.id), "role": role.name},
        )
        await self.session.commit()
        await self.session.refresh(user)  # load server-generated timestamps
        await self.session.refresh(user, ["role"])
        return UserOut.of(user)

    async def update(
        self,
        user_id: uuid.UUID,
        data: UpdateUserRequest,
        *,
        actor_id: uuid.UUID,
        actor_permissions: frozenset[Permission],
        meta: RequestMeta,
    ) -> UserOut:
        changes = data.model_dump(exclude_unset=True, exclude_none=True)
        # Changing one's own role or status could leave the organization
        # with no one able to manage users.
        if user_id == actor_id and {"role_id", "is_active"} & changes.keys():
            raise ForbiddenError("You cannot change your own role or active status.")

        user = await self.users.get(user_id)
        if {"role_id", "is_active"} & changes.keys():
            # Nor may anyone change a user who has more access than they do
            # (e.g. a custom "HR" role demoting an Admin).
            check_within(user.role, actor_permissions)
        if "role_id" in changes:
            role = await self.roles.get(changes["role_id"])
            check_within(role, actor_permissions)
            user.role_id = role.id
        if "full_name" in changes:
            user.full_name = changes["full_name"]
        if "is_active" in changes:
            user.is_active = changes["is_active"]
        record_audit(
            self.session,
            tenant_id=self.tenant_id,
            actor_user_id=actor_id,
            action="user.update",
            resource_type="user",
            resource_id=user.id,
            meta=meta,
            # Field names plus security-relevant values; names are personal data.
            metadata={
                "fields": sorted(changes),
                **{k: str(changes[k]) for k in ("role_id", "is_active") if k in changes},
            },
        )
        await self.session.commit()
        if {"role_id", "is_active"} & changes.keys():
            # After the commit: a refresh that races this sees the new state.
            await revoke_user_sessions(self.redis, user.id, ttl_s=self.revoke_ttl_s)
        await self.session.refresh(user)
        await self.session.refresh(user, ["role"])
        return UserOut.of(user)
