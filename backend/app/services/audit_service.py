"""
Audit trail writes.

Entries are added to the caller's session so they commit (or roll back)
atomically with the action they describe: an audit row can never claim an
action that did not persist.
"""

from __future__ import annotations

import ipaddress
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import request_id_ctx
from app.db.models import AuditLog


@dataclass(frozen=True)
class RequestMeta:
    """Request facts recorded with audit entries."""

    ip_address: str | None = None

    @classmethod
    def from_client_host(cls, host: str | None) -> RequestMeta:
        # The column is INET; anything that is not an IP (e.g. a test
        # client's placeholder host) is dropped rather than failing the insert.
        try:
            return cls(str(ipaddress.ip_address(host))) if host else cls()
        except ValueError:
            return cls()


def record_audit(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID | str | None = None,
    actor_user_id: uuid.UUID | None = None,
    meta: RequestMeta | None = None,
    metadata: dict[str, object] | None = None,
) -> None:
    """Stage an audit entry. `metadata` holds IDs and field names only —
    never passwords, tokens or contract text."""
    session.add(
        AuditLog(
            organization_id=tenant_id,
            actor_user_id=actor_user_id,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id is not None else None,
            request_id=request_id_ctx.get(),
            ip_address=meta.ip_address if meta else None,
            metadata_=metadata or {},
        )
    )
