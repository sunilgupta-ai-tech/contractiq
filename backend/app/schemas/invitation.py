"""Invitations to join an organization (Phase 22)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.auth import FullName, NewEmail, NewPassword, PersonalPasswordCheck


class CreateInvitationRequest(BaseModel):
    email: NewEmail
    role_id: uuid.UUID


class InvitationOut(BaseModel):
    id: uuid.UUID
    email: str
    role_id: uuid.UUID
    role_name: str
    expires_at: datetime
    created_at: datetime


class InvitationCreated(InvitationOut):
    """Returned once, at creation: the link's token is never shown again."""

    token: str


class InvitationPreview(BaseModel):
    """What the invitee sees before accepting."""

    email: str
    organization_name: str
    role_name: str
    expires_at: datetime


class AcceptInvitationRequest(PersonalPasswordCheck):
    full_name: FullName
    password: NewPassword
