"""
Custom roles within one organization (Phase 17).

Rules that keep role management safe:

* System roles (Admin, Manager, Employee, Viewer) cannot be edited or
  deleted; they are shared by every organization.
* No escalation: a role can only contain permissions its author holds.
* Nobody edits the role they hold themselves — otherwise a custom
  "Team lead" with role management could grant itself user management.
* A role in use cannot be deleted; move its members to another role first.
* Changing a role's permissions revokes the organization's access tokens,
  so every member of the role gets the new permissions at once.
"""

from __future__ import annotations

import uuid

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, ForbiddenError
from app.core.security import Permission
from app.core.sessions import revoke_org_sessions
from app.db.models import Role
from app.db.repositories.role_repository import RoleRepository
from app.schemas.user import CreateRoleRequest, PermissionOut, RoleOut, UpdateRoleRequest
from app.services.audit_service import RequestMeta, record_audit
from app.services.user_service import BEYOND_OWN

SYSTEM_ROLE_LOCKED = "Built-in roles cannot be changed. Create a custom role instead."
NAME_TAKEN = "A role with this name already exists."


class RoleService:
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
        self.roles = RoleRepository(session, tenant_id)

    @staticmethod
    def permissions() -> list[PermissionOut]:
        return PermissionOut.catalog()

    async def list(self) -> list[RoleOut]:
        counts = await self.roles.member_counts()
        return [RoleOut.of(r, counts.get(r.id, 0)) for r in await self.roles.list()]

    async def create(
        self,
        data: CreateRoleRequest,
        *,
        actor_id: uuid.UUID,
        actor_permissions: frozenset[Permission],
        meta: RequestMeta,
    ) -> RoleOut:
        permissions = frozenset(data.permissions)
        if not permissions <= actor_permissions:
            raise ForbiddenError(BEYOND_OWN)
        if await self.roles.name_taken(data.name):
            raise ConflictError(NAME_TAKEN)
        role = Role(name=data.name, description=data.description)
        role.permissions = permissions
        await self.roles.add(role)
        self._audit("role.create", role, actor_id, meta, sorted(permissions))
        await self.session.commit()
        return RoleOut.of(role)

    async def update(
        self,
        role_id: uuid.UUID,
        data: UpdateRoleRequest,
        *,
        actor_id: uuid.UUID,
        actor_role_id: uuid.UUID,
        actor_permissions: frozenset[Permission],
        meta: RequestMeta,
    ) -> RoleOut:
        role = await self._editable(role_id, actor_role_id)
        changes = data.model_dump(exclude_unset=True, exclude_none=True)
        if "name" in changes and changes["name"].lower() != role.name.lower():
            if await self.roles.name_taken(changes["name"], exclude=role.id):
                raise ConflictError(NAME_TAKEN)
            role.name = changes["name"]
        if "description" in changes:
            role.description = changes["description"]
        permissions_changed = False
        if "permissions" in changes:
            permissions = frozenset(data.permissions or [])
            if not permissions <= actor_permissions:
                raise ForbiddenError(BEYOND_OWN)
            permissions_changed = permissions != role.permissions
            role.permissions = permissions
        self._audit("role.update", role, actor_id, meta, sorted(changes))
        await self.session.commit()
        if permissions_changed:
            await revoke_org_sessions(self.redis, self.tenant_id, ttl_s=self.revoke_ttl_s)
        counts = await self.roles.member_counts()
        return RoleOut.of(role, counts.get(role.id, 0))

    async def delete(
        self,
        role_id: uuid.UUID,
        *,
        actor_id: uuid.UUID,
        actor_role_id: uuid.UUID,
        meta: RequestMeta,
    ) -> None:
        role = await self._editable(role_id, actor_role_id)
        members = (await self.roles.member_counts()).get(role.id, 0)
        if members:
            raise ConflictError(
                f"{members} user(s) have this role. Give them another role first.",
                details={"member_count": members},
            )
        self._audit("role.delete", role, actor_id, meta, [])
        await self.session.delete(role)
        await self.session.commit()

    async def _editable(self, role_id: uuid.UUID, actor_role_id: uuid.UUID) -> Role:
        role = await self.roles.get(role_id)
        if role.is_system:
            raise ForbiddenError(SYSTEM_ROLE_LOCKED)
        if role.id == actor_role_id:
            raise ForbiddenError("You cannot change the role you hold yourself.")
        return role

    def _audit(
        self, action: str, role: Role, actor_id: uuid.UUID, meta: RequestMeta, detail: list[str]
    ) -> None:
        record_audit(
            self.session,
            tenant_id=self.tenant_id,
            actor_user_id=actor_id,
            action=action,
            resource_type="role",
            resource_id=role.id,
            meta=meta,
            metadata={"name": role.name, "detail": detail},
        )
