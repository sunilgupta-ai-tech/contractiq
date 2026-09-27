"""
Roles visible to one organization: the shared system roles plus its own
custom roles (Phase 17). Scoped here in code and, independently, by
row-level security in the database.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.models import Role, User


class RoleRepository:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id

    def _visible(self) -> Select[tuple[Role]]:
        return select(Role).where(
            or_(Role.organization_id.is_(None), Role.organization_id == self.tenant_id)
        )

    async def list(self) -> Sequence[Role]:
        """System roles first (in their fixed order), then custom roles by name."""
        stmt = self._visible().order_by(Role.is_system.desc(), Role.id, func.lower(Role.name))
        rows = (await self.session.execute(stmt)).scalars().all()
        system = sorted((r for r in rows if r.is_system), key=lambda r: r.id)
        custom = sorted((r for r in rows if not r.is_system), key=lambda r: r.name.lower())
        return [*system, *custom]

    async def get(self, role_id: uuid.UUID) -> Role:
        """A role this organization may assign. Another organization's custom
        role is reported as not found, like any unknown ID."""
        role = (
            await self.session.execute(self._visible().where(Role.id == role_id))
        ).scalar_one_or_none()
        if role is None:
            raise NotFoundError("Role not found.")
        return role

    async def name_taken(self, name: str, *, exclude: uuid.UUID | None = None) -> bool:
        stmt = self._visible().where(func.lower(Role.name) == name.lower())
        if exclude is not None:
            stmt = stmt.where(Role.id != exclude)
        return (await self.session.execute(stmt.limit(1))).first() is not None

    async def add(self, role: Role) -> Role:
        role.organization_id = self.tenant_id
        role.is_system = False
        self.session.add(role)
        await self.session.flush()
        return role

    async def member_counts(self) -> dict[uuid.UUID, int]:
        stmt = (
            select(User.role_id, func.count())
            .where(User.organization_id == self.tenant_id)
            .group_by(User.role_id)
        )
        return {role_id: int(n) for role_id, n in (await self.session.execute(stmt)).all()}
