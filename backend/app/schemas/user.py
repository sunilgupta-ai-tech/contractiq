"""Request/response schemas for user management."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.core.security import Role
from app.schemas.auth import Email, FullName, NewPassword


class UserOut(BaseModel):
    """Public view of a user. Never includes the password hash."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    email: str
    full_name: str
    role: Role
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime


class CreateUserRequest(BaseModel):
    """An ADMIN adds a user to their own organization."""

    email: Email
    full_name: FullName
    password: NewPassword
    role: Role = Role.VIEWER


class UpdateUserRequest(BaseModel):
    """Partial update; omitted fields are left unchanged."""

    full_name: FullName | None = None
    role: Role | None = None
    is_active: bool | None = None
