from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.security import SystemRole
from app.db.database import Base
from app.db.models.base import TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.models.role import SYSTEM_ROLE_IDS, Role

if TYPE_CHECKING:
    from app.db.models.organization import Organization


class User(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # Phase 17: a row in `roles` (system or the organization's own). A role
    # in use cannot be deleted (RESTRICT).
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="RESTRICT"),
        default=SYSTEM_ROLE_IDS[SystemRole.VIEWER],
        nullable=False,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    organization: Mapped[Organization] = relationship(back_populates="users")
    role: Mapped[Role] = relationship(lazy="joined")
