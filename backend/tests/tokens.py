"""Access tokens for tests: a user holding one of the system roles."""

from __future__ import annotations

import uuid

from app.core.config import Settings
from app.core.security import (
    SYSTEM_ROLE_PERMISSIONS,
    Permission,
    SystemRole,
    TokenType,
    create_token,
)
from app.db.models.role import SYSTEM_ROLE_IDS, SYSTEM_ROLE_NAMES


def perms(role: SystemRole) -> frozenset[Permission]:
    return SYSTEM_ROLE_PERMISSIONS[role]


def token_for(
    settings: Settings,
    role: SystemRole = SystemRole.VIEWER,
    *,
    subject: str | None = None,
    tenant_id: str | None = None,
    token_type: TokenType = "access",  # noqa: S107
) -> str:
    return create_token(
        settings,
        subject=subject or str(uuid.uuid4()),
        tenant_id=tenant_id or str(uuid.uuid4()),
        role=SYSTEM_ROLE_NAMES[role],
        role_id=str(SYSTEM_ROLE_IDS[role]),
        permissions=SYSTEM_ROLE_PERMISSIONS[role],
        token_type=token_type,
    )
