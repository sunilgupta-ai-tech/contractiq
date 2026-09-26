"""
Database-level tenant isolation (Phase 15): PostgreSQL row-level security.

Repositories already filter every query by `organization_id`
(`TenantScopedRepository`). Row-level security is the second, independent
layer: once a session is bound to a tenant, every transaction it runs
switches to the `app_tenant` role, whose policies only let it see and write
rows of that tenant. A query that forgets its filter then returns the
tenant's own rows, never another company's.

How a session is bound:
- API: `get_tenant_session` binds the request's session to the tenant in
  the signed token, before any service touches the database.
- Worker: tasks call `bind_tenant` as soon as they know the job's tenant.

Every transaction begins with `SET LOCAL ROLE app_tenant` and the tenant id
in the transaction-local setting `app.tenant_id`, so both reset
automatically at commit or rollback, and a pooled connection never carries
one request's tenant into the next. Without a tenant, the policies match
nothing (`current_setting` returns NULL), so they fail closed.

Unbound sessions (sign-in, registration, token refresh, the worker's
job lookup by id) run as the connection's own role, as before. They need
to find a user or job before the tenant is known.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransaction

# Created by migration 20260926_rls; the login role is granted membership.
TENANT_ROLE = "app_tenant"
TENANT_SETTING = "app.tenant_id"
_INFO_KEY = "tenant_id"

_SET_ROLE = text(f"SET LOCAL ROLE {TENANT_ROLE}")
_SET_TENANT = text(f"SELECT set_config('{TENANT_SETTING}', :tenant_id, true)")


def _apply(connection: Connection, tenant_id: str) -> None:
    connection.execute(_SET_ROLE)
    connection.execute(_SET_TENANT, {"tenant_id": tenant_id})


def _after_begin(session: Session, transaction: SessionTransaction, connection: Connection) -> None:
    tenant_id = session.info.get(_INFO_KEY)
    if tenant_id is not None:
        _apply(connection, tenant_id)


def install(session_class: type[Session]) -> None:
    """Register the per-transaction hook on a session class (idempotent)."""
    if not event.contains(session_class, "after_begin", _after_begin):
        event.listen(session_class, "after_begin", _after_begin)


class TenantAwareSession(Session):
    """Sync session class behind every `AsyncSession` of the app."""


install(TenantAwareSession)


async def bind_tenant(session: AsyncSession, tenant_id: uuid.UUID | str) -> None:
    """Restrict `session` to one tenant for the rest of its life.

    Applies to the transaction already open (if any) and, through the
    `after_begin` hook, to every later one. Rebinding to a different tenant
    is refused: one session never serves two tenants."""
    value = str(uuid.UUID(str(tenant_id)))
    current: Any = session.info.get(_INFO_KEY)
    if current is not None and current != value:
        raise RuntimeError("session is already bound to another tenant")
    session.info[_INFO_KEY] = value
    if current is None and session.in_transaction():
        await session.execute(_SET_ROLE)
        await session.execute(_SET_TENANT, {"tenant_id": value})


def bound_tenant(session: AsyncSession) -> str | None:
    return session.info.get(_INFO_KEY)  # type: ignore[no-any-return]
