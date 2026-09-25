"""
Tenant-scoped repository base.

Tenant isolation is enforced here, structurally: a repository is constructed
with a tenant ID and every query it builds is filtered by it. There is no
method that reads tenant-owned rows without that filter, so a missing
`WHERE organization_id = ...` cannot happen by omission in a service.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, Generic, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.database import Base

ModelT = TypeVar("ModelT", bound=Base)


class TenantScopedRepository(Generic[ModelT]):
    model: type[ModelT]

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        if not hasattr(self.model, "organization_id"):
            raise TypeError(f"{self.model.__name__} is not tenant-owned")
        self.session = session
        self.tenant_id = tenant_id

    def _scoped(self) -> Select[tuple[ModelT]]:
        return select(self.model).where(self.model.organization_id == self.tenant_id)  # type: ignore[attr-defined]

    async def get(self, entity_id: uuid.UUID) -> ModelT:
        """Fetch by ID within the tenant. A row owned by another tenant is
        reported as NOT_FOUND (not FORBIDDEN) so IDs can't be probed."""
        stmt = self._scoped().where(self.model.id == entity_id)  # type: ignore[attr-defined]
        entity = (await self.session.execute(stmt)).scalar_one_or_none()
        if entity is None:
            raise NotFoundError()
        return entity

    async def list(self, *, offset: int = 0, limit: int = 50, **filters: Any) -> Sequence[ModelT]:
        stmt = self._scoped().filter_by(**filters).offset(offset).limit(min(limit, 200))
        return (await self.session.execute(stmt)).scalars().all()

    async def count(self, **filters: Any) -> int:
        stmt = select(func.count()).select_from(self._scoped().filter_by(**filters).subquery())
        return int((await self.session.execute(stmt)).scalar_one())

    async def add(self, entity: ModelT) -> ModelT:
        entity.organization_id = self.tenant_id  # type: ignore[attr-defined]
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def delete(self, entity_id: uuid.UUID) -> None:
        await self.session.delete(await self.get(entity_id))
