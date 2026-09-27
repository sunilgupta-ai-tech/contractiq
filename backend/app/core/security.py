"""
Password hashing, JWT handling and role definitions.

Authorization decisions are made here and in `dependencies.py` — in code —
never by the LLM. Full auth endpoints are wired in Phase 2; these primitives
are foundational and unit-tested now.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Literal

import bcrypt
import jwt

from app.core.config import Settings
from app.core.exceptions import UnauthorizedError

TokenType = Literal["access", "refresh"]

# Tokens say who they are for, so a tenant token is never accepted by the
# platform (super admin) API or the other way round (Phase 18).
TENANT_AUDIENCE = "docunexa:tenant"
PLATFORM_AUDIENCE = "docunexa:platform"


class SystemRole(StrEnum):
    """The four roles every organization starts with (Phase 17). They are
    rows in `roles` with fixed IDs (app/db/models/role.py) and cannot be
    edited or deleted; organizations add their own custom roles beside them."""

    ADMIN = "admin"
    MANAGER = "manager"
    EMPLOYEE = "employee"
    VIEWER = "viewer"


class Permission(StrEnum):
    """What a role may do. The catalog lives in code because code enforces
    it: a custom role is a named subset of these, never a new capability."""

    DOCUMENT_READ = "document:read"
    DOCUMENT_UPLOAD = "document:upload"
    DOCUMENT_DELETE = "document:delete"
    DOCUMENT_SHARE = "document:share"  # Phase 20: manage who sees a document
    DOCUMENT_READ_ALL = "document:read_all"  # Phase 20: see restricted documents too
    QUERY_RUN = "query:run"
    ANALYSIS_RUN = "analysis:run"
    EVALUATION_RUN = "evaluation:run"
    USER_MANAGE = "user:manage"
    ROLE_MANAGE = "role:manage"


@dataclass(frozen=True)
class PermissionInfo:
    group: str
    label: str
    description: str


# Shown in the role editor; every Permission must have an entry (unit-tested).
PERMISSION_INFO: dict[Permission, PermissionInfo] = {
    Permission.DOCUMENT_READ: PermissionInfo(
        "Documents", "View documents", "See the library, documents and their versions."
    ),
    Permission.DOCUMENT_UPLOAD: PermissionInfo(
        "Documents", "Upload documents", "Add documents and new versions."
    ),
    Permission.DOCUMENT_DELETE: PermissionInfo(
        "Documents", "Delete documents", "Permanently remove documents and all their versions."
    ),
    Permission.DOCUMENT_SHARE: PermissionInfo(
        "Documents",
        "Manage document access",
        "Restrict a document to chosen people or roles, or open it to everyone.",
    ),
    Permission.DOCUMENT_READ_ALL: PermissionInfo(
        "Documents",
        "See restricted documents",
        "See every document in the organization, including restricted ones.",
    ),
    Permission.QUERY_RUN: PermissionInfo(
        "Assistant", "Ask questions", "Use the Assistant to ask questions across documents."
    ),
    Permission.ANALYSIS_RUN: PermissionInfo(
        "Analysis", "Run analysis", "Clause extraction, summaries, risk review and comparison."
    ),
    Permission.EVALUATION_RUN: PermissionInfo(
        "Analysis", "Run evaluations", "Measure answer quality against a test set."
    ),
    Permission.USER_MANAGE: PermissionInfo(
        "Administration", "Manage users", "Add users, change their role, deactivate them."
    ),
    Permission.ROLE_MANAGE: PermissionInfo(
        "Administration", "Manage roles", "Create and edit custom roles."
    ),
}

SYSTEM_ROLE_PERMISSIONS: dict[SystemRole, frozenset[Permission]] = {
    SystemRole.ADMIN: frozenset(Permission),
    SystemRole.MANAGER: frozenset(
        {
            Permission.DOCUMENT_READ,
            Permission.DOCUMENT_UPLOAD,
            Permission.DOCUMENT_DELETE,
            Permission.DOCUMENT_SHARE,
            Permission.QUERY_RUN,
            Permission.ANALYSIS_RUN,
            Permission.EVALUATION_RUN,
        }
    ),
    SystemRole.EMPLOYEE: frozenset(
        {
            Permission.DOCUMENT_READ,
            Permission.DOCUMENT_UPLOAD,
            Permission.QUERY_RUN,
            Permission.ANALYSIS_RUN,
        }
    ),
    SystemRole.VIEWER: frozenset({Permission.DOCUMENT_READ, Permission.QUERY_RUN}),
}


def parse_permissions(values: Iterable[str]) -> frozenset[Permission]:
    """Known permissions only: a value removed from the catalog in a later
    release is dropped instead of breaking every token or role that had it."""
    known = {p.value for p in Permission}
    return frozenset(Permission(v) for v in values if v in known)


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
    role: str,
    role_id: str,
    permissions: Iterable[Permission],
    token_type: TokenType = "access",  # noqa: S107
) -> str:
    """Create a signed JWT. `tenant_id` is embedded so every request is
    tenant-scoped before it reaches any repository or retriever; the role's
    permissions are embedded so authorization needs no database read.
    `ts` (milliseconds) lets a role or status change revoke tokens issued
    before it (app/core/sessions.py)."""
    now = datetime.now(UTC)
    lifetime = (
        timedelta(minutes=settings.access_token_expire_minutes)
        if token_type == "access"  # noqa: S105
        else timedelta(days=settings.refresh_token_expire_days)
    )
    claims: dict[str, Any] = {
        "sub": subject,
        "tid": tenant_id,
        "aud": TENANT_AUDIENCE,
        "role": role,
        "rid": role_id,
        "perms": sorted(p.value for p in permissions),
        "type": token_type,
        "iat": now,
        "ts": int(now.timestamp() * 1000),
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
            audience=TENANT_AUDIENCE,
            options={"require": ["sub", "tid", "aud", "role", "rid", "perms", "type", "ts", "exp"]},
        )
    except jwt.PyJWTError as exc:
        raise UnauthorizedError("Invalid or expired token.") from exc
    if claims["type"] != expected_type:
        raise UnauthorizedError("Invalid token type.")
    return claims


# --- Platform console tokens (Phase 18) ---------------------------------------------
# A separate audience and claim set: a tenant token is never a platform token,
# and a platform token carries no tenant, so it opens no tenant data.


def create_platform_token(
    settings: Settings,
    *,
    subject: str,
    role: str,
    token_type: TokenType = "access",  # noqa: S107
) -> str:
    now = datetime.now(UTC)
    lifetime = (
        timedelta(minutes=settings.access_token_expire_minutes)
        if token_type == "access"  # noqa: S105
        else timedelta(days=1)  # platform sessions are short: at most a day
    )
    claims: dict[str, Any] = {
        "sub": subject,
        "aud": PLATFORM_AUDIENCE,
        "prole": role,
        "type": token_type,
        "iat": now,
        "ts": int(now.timestamp() * 1000),
        "exp": now + lifetime,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(
        claims, settings.jwt_secret_key.get_secret_value(), algorithm=settings.jwt_algorithm
    )


def decode_platform_token(
    settings: Settings, token: str, expected_type: TokenType = "access"
) -> dict[str, Any]:
    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            audience=PLATFORM_AUDIENCE,
            options={"require": ["sub", "aud", "prole", "type", "ts", "exp"]},
        )
    except jwt.PyJWTError as exc:
        raise UnauthorizedError("Invalid or expired token.") from exc
    if claims["type"] != expected_type:
        raise UnauthorizedError("Invalid token type.")
    return claims
