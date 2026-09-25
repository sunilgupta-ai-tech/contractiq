"""
User management within one organization.

The service is constructed with the caller's tenant ID (from the signed
token) and every read and write goes through a tenant-scoped repository, so
an ADMIN of one organization cannot see or change users of another — a
foreign user ID is reported as not found.
"""

from __future__ import annotations

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, ForbiddenError
from app.core.security import hash_password
from app.db.models import User
from app.db.repositories.user_repository import UserRepository, find_user_by_email
from app.schemas.common import Page
from app.schemas.user import CreateUserRequest, UpdateUserRequest, UserOut
from app.services.audit_service import RequestMeta, record_audit
from app.services.auth_service import EMAIL_TAKEN


class UserService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.users = UserRepository(session, tenant_id)

    async def get(self, user_id: uuid.UUID) -> UserOut:
        return UserOut.model_validate(await self.users.get(user_id))

    async def list(self, *, offset: int, limit: int) -> Page[UserOut]:
        rows = await self.users.list(offset=offset, limit=limit)
        return Page(
            items=[UserOut.model_validate(u) for u in rows],
            total=await self.users.count(),
            offset=offset,
            limit=limit,
        )

    async def create(
        self, data: CreateUserRequest, *, actor_id: uuid.UUID, meta: RequestMeta
    ) -> UserOut:
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
                    role=data.role,
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
            metadata={"role": data.role.value},
        )
        await self.session.commit()
        await self.session.refresh(user)  # load server-generated timestamps
        return UserOut.model_validate(user)

    async def update(
        self,
        user_id: uuid.UUID,
        data: UpdateUserRequest,
        *,
        actor_id: uuid.UUID,
        meta: RequestMeta,
    ) -> UserOut:
        changes = data.model_dump(exclude_unset=True, exclude_none=True)
        # An ADMIN demoting or disabling themselves could leave the
        # organization with no one able to manage users.
        if user_id == actor_id and {"role", "is_active"} & changes.keys():
            raise ForbiddenError("You cannot change your own role or active status.")

        user = await self.users.get(user_id)
        for field, value in changes.items():
            setattr(user, field, value)
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
                **{k: changes[k] for k in ("role", "is_active") if k in changes},
            },
        )
        await self.session.commit()
        await self.session.refresh(user)
        return UserOut.model_validate(user)
