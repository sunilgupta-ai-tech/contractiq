"""
Roles (Phase 17): named sets of permissions.

System roles (Admin, Manager, Employee, Viewer) have `organization_id` NULL,
fixed IDs and `is_system` true: every organization sees them, nobody can
edit or delete them. Custom roles belong to one organization, and only its
users (with role:manage) can see or change them. Row-level security enforces
both (migration a3f1c9d2e7b4).

Permissions are stored as their string values; unknown values (from a
permission since removed from the catalog) are ignored when read.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.security import Permission, SystemRole, parse_permissions
from app.db.database import Base
from app.db.models.base import TimestampMixin, UUIDPrimaryKeyMixin

SYSTEM_ROLE_IDS: dict[SystemRole, uuid.UUID] = {
    SystemRole.ADMIN: uuid.UUID("00000000-0000-4000-8000-00000000a001"),
    SystemRole.MANAGER: uuid.UUID("00000000-0000-4000-8000-00000000a002"),
    SystemRole.EMPLOYEE: uuid.UUID("00000000-0000-4000-8000-00000000a003"),
    SystemRole.VIEWER: uuid.UUID("00000000-0000-4000-8000-00000000a004"),
}

SYSTEM_ROLE_NAMES: dict[SystemRole, str] = {
    SystemRole.ADMIN: "Admin",
    SystemRole.MANAGER: "Manager",
    SystemRole.EMPLOYEE: "Employee",
    SystemRole.VIEWER: "Viewer",
}

SYSTEM_ROLE_DESCRIPTIONS: dict[SystemRole, str] = {
    SystemRole.ADMIN: "Full access, including users and roles.",
    SystemRole.MANAGER: "Manage documents (including delete), ask, analyse, evaluate.",
    SystemRole.EMPLOYEE: "Upload documents, ask questions and run analysis.",
    SystemRole.VIEWER: "Read documents and ask questions.",
}


class Role(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)

    # NULL for the shared system roles; otherwise the owning organization.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    permission_values: Mapped[list[str]] = mapped_column(
        "permissions", JSONB, default=list, nullable=False
    )
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    @property
    def permissions(self) -> frozenset[Permission]:
        return parse_permissions(self.permission_values)

    @permissions.setter
    def permissions(self, value: frozenset[Permission] | set[Permission]) -> None:
        self.permission_values = sorted(p.value for p in value)
