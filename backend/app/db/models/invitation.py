"""
Invitations to join an organization (Phase 22).

An admin invites an email address with a role; the invitee opens the link,
chooses their own password and is signed in. Only a SHA-256 of the token is
stored, so a database leak does not yield usable invitation links. Links
expire and work once.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.base import TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Invitation(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "invitations"

    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    invited_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
