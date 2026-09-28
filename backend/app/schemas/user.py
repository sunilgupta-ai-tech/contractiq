"""Request/response schemas for users, roles and permissions (Phase 17)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from app.core.security import PERMISSION_INFO, Permission
from app.db.models import Role, User
from app.schemas.auth import FullName, NewEmail, NewPassword, PersonalPasswordCheck


class UserOut(BaseModel):
    """Public view of a user. Never includes the password hash."""

    id: uuid.UUID
    organization_id: uuid.UUID
    email: str
    full_name: str
    role_id: uuid.UUID
    role_name: str
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime

    @classmethod
    def of(cls, user: User) -> UserOut:
        return cls(
            id=user.id,
            organization_id=user.organization_id,
            email=user.email,
            full_name=user.full_name,
            role_id=user.role_id,
            role_name=user.role.name,
            is_active=user.is_active,
            last_login_at=user.last_login_at,
            created_at=user.created_at,
        )


class MeOut(UserOut):
    """GET /users/me: the caller plus their organization, for the app shell.
    `permissions` lets the UI show only the actions the user may take; the
    API enforces them regardless."""

    organization_name: str
    member_count: int
    permissions: list[Permission]


class CreateUserRequest(PersonalPasswordCheck):
    """An admin adds a user to their own organization. Without `role_id`
    the user gets the Viewer role."""

    email: NewEmail
    full_name: FullName
    password: NewPassword
    role_id: uuid.UUID | None = None


class UpdateUserRequest(BaseModel):
    """Partial update; omitted fields are left unchanged."""

    full_name: FullName | None = None
    role_id: uuid.UUID | None = None
    is_active: bool | None = None


# --- Roles ---------------------------------------------------------------------------

RoleName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=80)]
RoleDescription = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]


class PermissionOut(BaseModel):
    key: Permission
    group: str
    label: str
    description: str

    @classmethod
    def catalog(cls) -> list[PermissionOut]:
        return [
            cls(key=p, group=i.group, label=i.label, description=i.description)
            for p, i in PERMISSION_INFO.items()
        ]


class RoleOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    permissions: list[Permission]
    is_system: bool
    member_count: int

    @classmethod
    def of(cls, role: Role, member_count: int = 0) -> RoleOut:
        return cls(
            id=role.id,
            name=role.name,
            description=role.description,
            permissions=sorted(role.permissions),
            is_system=role.is_system,
            member_count=member_count,
        )


class CreateRoleRequest(BaseModel):
    name: RoleName
    description: RoleDescription = ""
    permissions: list[Permission] = Field(min_length=1)


class UpdateRoleRequest(BaseModel):
    name: RoleName | None = None
    description: RoleDescription | None = None
    permissions: list[Permission] | None = Field(default=None, min_length=1)
