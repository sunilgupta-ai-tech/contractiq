"""
The platform operator's side (Phase 18): the people who run DocuNexa AI and
the record of what they did.

Platform admins are a separate identity from organization users — their own
table, sign-in and token audience — so no organization account can ever be
promoted into the platform console, and a platform admin has no access to
any organization's documents or answers. These tables have no
`organization_id` and no row-level-security grant: tenant sessions cannot
read them at all.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class PlatformRole(StrEnum):
    SUPER_ADMIN = "SUPER_ADMIN"  # everything, including other platform admins
    SUPPORT = "SUPPORT"  # read-only: organizations, usage, audit


class PlatformAdmin(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "platform_admins"

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[PlatformRole] = mapped_column(
        Enum(PlatformRole, name="platform_role"), default=PlatformRole.SUPPORT, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PlatformAuditLog(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Every platform action: sign-ins, status and plan changes, admin changes."""

    __tablename__ = "platform_audit_logs"

    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_admins.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    target_type: Mapped[str | None] = mapped_column(String(50))
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"), index=True
    )
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64))
