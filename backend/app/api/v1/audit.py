"""
The organization's audit log (Phase 22), for administrators: sign-ins,
uploads, downloads, deletions, access changes, AI questions, user and role
changes. Entries carry IDs and parameters only — never document text or
questions — so the log itself is safe to show and export.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.core.dependencies import TenantSession, UserManagerDep
from app.db.models import AuditLog, User
from app.schemas.common import ApiResponse, Page

router = APIRouter(tags=["audit"])


class AuditEntryOut(BaseModel):
    id: uuid.UUID
    action: str
    actor_id: uuid.UUID | None
    actor_name: str | None
    actor_email: str | None
    resource_type: str
    resource_id: str | None
    ip_address: str | None
    metadata: dict[str, Any]
    created_at: datetime


@router.get(
    "/audit-logs",
    summary="The organization's audit log, newest first",
    response_model=ApiResponse[Page[AuditEntryOut]],
)
async def list_audit_logs(
    admin: UserManagerDep,
    session: TenantSession,
    action: Annotated[
        str | None, Query(max_length=100, description="Exact action or a prefix like 'document.'")
    ] = None,
    actor_id: Annotated[uuid.UUID | None, Query()] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ApiResponse[Page[AuditEntryOut]]:
    filters = [AuditLog.organization_id == admin.tenant_id]
    if action:
        filters.append(
            AuditLog.action.startswith(action)
            if action.endswith(".")
            else AuditLog.action == action
        )
    if actor_id is not None:
        filters.append(AuditLog.actor_user_id == actor_id)
    total = await session.scalar(select(func.count()).select_from(AuditLog).where(*filters))
    rows = (
        await session.execute(
            select(AuditLog, User.full_name, User.email)
            .outerjoin(User, User.id == AuditLog.actor_user_id)
            .where(*filters)
            .order_by(AuditLog.created_at.desc(), AuditLog.id)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    items = [
        AuditEntryOut(
            id=entry.id,
            action=entry.action,
            actor_id=entry.actor_user_id,
            actor_name=name,
            actor_email=email,
            resource_type=entry.resource_type,
            resource_id=entry.resource_id,
            ip_address=str(entry.ip_address) if entry.ip_address else None,
            metadata=dict(entry.metadata_ or {}),
            created_at=entry.created_at,
        )
        for entry, name, email in rows
    ]
    return ApiResponse(data=Page(items=items, total=int(total or 0), offset=offset, limit=limit))
