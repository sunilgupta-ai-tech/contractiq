"""
Password hashing, JWT handling and role definitions.

Authorization decisions are made here and in `dependencies.py` — in code —
never by the LLM. Full auth endpoints are wired in Phase 2; these primitives
are foundational and unit-tested now.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Literal

import bcrypt
import jwt

from app.core.config import Settings
from app.core.exceptions import UnauthorizedError

TokenType = Literal["access", "refresh"]


class Role(StrEnum):
    ADMIN = "ADMIN"
    LEGAL_MANAGER = "LEGAL_MANAGER"
    ANALYST = "ANALYST"
    VIEWER = "VIEWER"


class Permission(StrEnum):
    DOCUMENT_READ = "document:read"
    DOCUMENT_UPLOAD = "document:upload"
    DOCUMENT_DELETE = "document:delete"
    QUERY_RUN = "query:run"
    ANALYSIS_RUN = "analysis:run"
    USER_MANAGE = "user:manage"
    EVALUATION_RUN = "evaluation:run"


ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.ADMIN: frozenset(Permission),
    Role.LEGAL_MANAGER: frozenset(
        {
            Permission.DOCUMENT_READ,
            Permission.DOCUMENT_UPLOAD,
            Permission.DOCUMENT_DELETE,
            Permission.QUERY_RUN,
            Permission.ANALYSIS_RUN,
            Permission.EVALUATION_RUN,
        }
    ),
    Role.ANALYST: frozenset(
        {
            Permission.DOCUMENT_READ,
            Permission.DOCUMENT_UPLOAD,
            Permission.QUERY_RUN,
            Permission.ANALYSIS_RUN,
        }
    ),
    Role.VIEWER: frozenset({Permission.DOCUMENT_READ, Permission.QUERY_RUN}),
}


def has_permission(role: Role, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, frozenset())


def hash_password(password: str) -> str:
    """bcrypt with a per-password salt. bcrypt truncates at 72 bytes; we
    reject longer inputs at the schema layer rather than silently truncate."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def create_token(
    settings: Settings,
    *,
    subject: str,
    tenant_id: str,
    role: Role,
    token_type: TokenType = "access",  # noqa: S107
) -> str:
    """Create a signed JWT. `tenant_id` is embedded so every request is
    tenant-scoped before it reaches any repository or retriever."""
    now = datetime.now(UTC)
    lifetime = (
        timedelta(minutes=settings.access_token_expire_minutes)
        if token_type == "access"  # noqa: S105
        else timedelta(days=settings.refresh_token_expire_days)
    )
    claims: dict[str, Any] = {
        "sub": subject,
        "tid": tenant_id,
        "role": role.value,
        "type": token_type,
        "iat": now,
        "exp": now + lifetime,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(
        claims, settings.jwt_secret_key.get_secret_value(), algorithm=settings.jwt_algorithm
    )


def decode_token(
    settings: Settings, token: str, expected_type: TokenType = "access"
) -> dict[str, Any]:
    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "tid", "role", "type", "exp"]},
        )
    except jwt.PyJWTError as exc:
        raise UnauthorizedError("Invalid or expired token.") from exc
    if claims["type"] != expected_type:
        raise UnauthorizedError("Invalid token type.")
    return claims
