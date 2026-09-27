"""
Plans and their limits (Phase 18).

A plan gives an organization default limits; the platform admin can
override any limit per organization (NULL = unlimited). Limits are checked
where usage grows:

    users      adding a user, or re-activating one      (UserService)
    documents  uploading a new document                  (DocumentService)
    storage    uploading any file, new document or version

Limits never delete or hide anything: an organization over its limit (say
after a downgrade) keeps its data and simply cannot add more.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import PlanLimitError
from app.db.models import Document, DocumentVersion, Organization, Plan, User

MB = 1024 * 1024


@dataclass(frozen=True)
class PlanLimits:
    max_users: int | None
    max_documents: int | None
    max_storage_mb: int | None
    # Phase 22: AI usage per calendar month.
    max_ai_queries_month: int | None = None
    max_ai_tokens_month: int | None = None


PLAN_LIMITS: dict[Plan, PlanLimits] = {
    Plan.FREE: PlanLimits(5, 200, 2 * 1024, 500, 1_000_000),
    Plan.STARTER: PlanLimits(25, 2_000, 20 * 1024, 5_000, 10_000_000),
    Plan.BUSINESS: PlanLimits(100, 20_000, 200 * 1024, 20_000, 40_000_000),
    Plan.ENTERPRISE: PlanLimits(None, None, None, None, None),
}


def apply_plan(organization: Organization, plan: Plan) -> None:
    """Switch plan and reset the limits to the plan's defaults."""
    limits = PLAN_LIMITS[plan]
    organization.plan = plan
    organization.max_users = limits.max_users
    organization.max_documents = limits.max_documents
    organization.max_storage_mb = limits.max_storage_mb
    organization.max_ai_queries_month = limits.max_ai_queries_month
    organization.max_ai_tokens_month = limits.max_ai_tokens_month


@dataclass(frozen=True)
class Usage:
    active_users: int
    documents: int
    storage_bytes: int


async def usage_of(session: AsyncSession, org_id: uuid.UUID) -> Usage:
    users = await session.scalar(
        select(func.count()).where(User.organization_id == org_id, User.is_active.is_(True))
    )
    documents = await session.scalar(
        select(func.count()).select_from(Document).where(Document.organization_id == org_id)
    )
    storage = await session.scalar(
        select(func.coalesce(func.sum(DocumentVersion.size_bytes), 0)).where(
            DocumentVersion.organization_id == org_id
        )
    )
    return Usage(int(users or 0), int(documents or 0), int(storage or 0))


async def _organization(session: AsyncSession, org_id: uuid.UUID) -> Organization | None:
    return await session.get(Organization, org_id)


async def ensure_can_add_user(session: AsyncSession, org_id: uuid.UUID) -> None:
    org = await _organization(session, org_id)
    if org is None or org.max_users is None:
        return
    if (await usage_of(session, org_id)).active_users >= org.max_users:
        raise PlanLimitError(
            f"Your plan allows {org.max_users} active users. "
            "Deactivate a user or ask for a larger plan.",
            details={"limit": "users", "max": org.max_users},
        )


async def ensure_can_upload(
    session: AsyncSession, org_id: uuid.UUID, *, new_document: bool, size_bytes: int
) -> None:
    org = await _organization(session, org_id)
    if org is None or (org.max_documents is None and org.max_storage_mb is None):
        return
    used = await usage_of(session, org_id)
    if new_document and org.max_documents is not None and used.documents >= org.max_documents:
        raise PlanLimitError(
            f"Your plan allows {org.max_documents:,} documents. "
            "Delete some or ask for a larger plan.",
            details={"limit": "documents", "max": org.max_documents},
        )
    if org.max_storage_mb is not None and used.storage_bytes + size_bytes > org.max_storage_mb * MB:
        raise PlanLimitError(
            f"Your plan's {org.max_storage_mb:,} MB of storage is full. "
            "Delete some documents or ask for a larger plan.",
            details={"limit": "storage", "max_mb": org.max_storage_mb},
        )
