from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.db.models.base import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.db.models.user import User


class OrganizationStatus(StrEnum):
    """Set by the platform console (Phase 18). A suspended organization's
    users cannot sign in, and their open sessions end at once."""

    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DELETING = "DELETING"  # Phase 22: access ended; data being erased in the background


class Plan(StrEnum):
    FREE = "FREE"
    STARTER = "STARTER"
    BUSINESS = "BUSINESS"
    ENTERPRISE = "ENTERPRISE"


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A tenant. Every document, conversation and audit record belongs to one."""

    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    status: Mapped[OrganizationStatus] = mapped_column(
        Enum(OrganizationStatus, name="organization_status"),
        default=OrganizationStatus.ACTIVE,
        server_default=OrganizationStatus.ACTIVE.value,
        nullable=False,
        index=True,
    )
    suspended_reason: Mapped[str | None] = mapped_column(String(300))
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The plan sets the default limits (app/services/plans.py); the platform
    # admin may override each one. NULL = unlimited.
    plan: Mapped[Plan] = mapped_column(
        Enum(Plan, name="organization_plan"),
        default=Plan.FREE,
        server_default=Plan.FREE.value,
        nullable=False,
    )
    max_users: Mapped[int | None] = mapped_column(Integer)
    max_documents: Mapped[int | None] = mapped_column(Integer)
    max_storage_mb: Mapped[int | None] = mapped_column(Integer)
    # Phase 22: AI usage per calendar month (UTC). NULL = unlimited.
    max_ai_queries_month: Mapped[int | None] = mapped_column(Integer)
    max_ai_tokens_month: Mapped[int | None] = mapped_column(BigInteger)

    users: Mapped[list[User]] = relationship(back_populates="organization")

    @property
    def is_active(self) -> bool:
        return self.status is OrganizationStatus.ACTIVE
