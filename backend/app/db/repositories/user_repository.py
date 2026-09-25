from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Organization, User
from app.db.repositories.base import TenantScopedRepository


class UserRepository(TenantScopedRepository[User]):
    model = User

    async def list(self, *, offset: int = 0, limit: int = 50, **filters: Any) -> Sequence[User]:
        # Stable ordering so offset pagination never skips or repeats rows.
        stmt = (
            self._scoped()
            .filter_by(**filters)
            .order_by(User.created_at, User.id)
            .offset(offset)
            .limit(min(limit, 200))
        )
        return (await self.session.execute(stmt)).scalars().all()


# --- Pre-authentication lookups ------------------------------------------------
# These are the only reads of tenant-owned rows that are not tenant-scoped:
# before sign-in there is no tenant yet, and the email (unique platform-wide)
# is what identifies it. They are used by AuthService alone and return data
# only to it; nothing here is reachable with a client-supplied tenant ID.


async def find_user_by_email(session: AsyncSession, email: str) -> User | None:
    stmt = select(User).where(func.lower(User.email) == email.lower())
    return (await session.execute(stmt)).scalar_one_or_none()


async def find_user_in_tenant(
    session: AsyncSession, user_id: uuid.UUID, tenant_id: uuid.UUID
) -> User | None:
    """Resolve a refresh token's subject. Matching on both IDs means a token
    can only ever resolve to a user in the tenant it was issued for."""
    stmt = select(User).where(User.id == user_id, User.organization_id == tenant_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_organization(session: AsyncSession, org_id: uuid.UUID) -> Organization | None:
    return await session.get(Organization, org_id)
