"""Request/response schemas for the platform console (Phase 18)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, Field, model_validator

from app.db.models import FileType, OrganizationStatus, Plan, PlatformRole
from app.schemas.auth import Email, FullName, NewPassword

Limit = Annotated[int, Field(ge=0, le=100_000_000)]


class PlatformAdminOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    email: str
    full_name: str
    role: PlatformRole
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime


class CreatePlatformAdminRequest(BaseModel):
    email: Email
    full_name: FullName
    password: NewPassword
    role: PlatformRole = PlatformRole.SUPPORT


class UpdatePlatformAdminRequest(BaseModel):
    role: PlatformRole | None = None
    is_active: bool | None = None


class LimitsOut(BaseModel):
    max_users: int | None
    max_documents: int | None
    max_storage_mb: int | None


class UsageOut(BaseModel):
    active_users: int
    total_users: int
    documents: int
    storage_bytes: int


class OrganizationSummary(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    status: OrganizationStatus
    plan: Plan
    limits: LimitsOut
    usage: UsageOut
    last_active_at: datetime | None
    created_at: datetime


class OrganizationMember(BaseModel):
    """Who is in an organization — names, emails and roles only. The console
    never shows documents, questions or answers."""

    id: uuid.UUID
    email: str
    full_name: str
    role_name: str
    is_active: bool
    last_login_at: datetime | None


class OrganizationDetail(OrganizationSummary):
    suspended_reason: str | None
    suspended_at: datetime | None
    documents_by_type: dict[FileType, int]
    failed_documents: int
    members: list[OrganizationMember]


class UpdateOrganizationRequest(BaseModel):
    """Status, plan and limits. Choosing a plan resets the limits to its
    defaults unless limits are given in the same request."""

    status: OrganizationStatus | None = None
    suspended_reason: Annotated[str, Field(max_length=300)] | None = None
    plan: Plan | None = None
    max_users: Limit | None = None
    max_documents: Limit | None = None
    max_storage_mb: Limit | None = None
    # Explicitly clear a limit (unlimited). Listed names are set to NULL.
    unlimited: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> UpdateOrganizationRequest:
        allowed = {"max_users", "max_documents", "max_storage_mb"}
        if set(self.unlimited) - allowed:
            raise ValueError(f"unlimited may only name {sorted(allowed)}")
        if (
            self.status is OrganizationStatus.SUSPENDED
            and not (self.suspended_reason or "").strip()
        ):
            raise ValueError("Give a reason when suspending an organization.")
        return self


class UpdateMemberRequest(BaseModel):
    is_active: bool


class PlatformOverview(BaseModel):
    organizations: int
    active_organizations: int
    suspended_organizations: int
    users: int
    active_users: int
    documents: int
    storage_bytes: int
    failed_documents_24h: int
    organizations_by_plan: dict[Plan, int]
    new_organizations_30d: int


class PlatformAuditOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    actor_id: uuid.UUID | None
    actor_email: str | None = None
    action: str
    target_type: str | None
    target_id: uuid.UUID | None
    organization_id: uuid.UUID | None
    details: dict[str, Any]
    ip_address: str | None
    created_at: datetime


class PlanOut(BaseModel):
    plan: Plan
    limits: LimitsOut
