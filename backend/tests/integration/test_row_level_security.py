"""Phase 15: PostgreSQL row-level security as the second tenant-isolation
layer. These tests deliberately run queries *without* an organization filter
— the mistake RLS exists to contain — and check that a tenant-bound session
still only reaches its own rows."""

import os
import uuid

import pytest
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app.core.config import Settings
from app.db.database import Database
from app.db.models import Organization, User
from app.db.tenancy import bind_tenant
from tests.integration.conftest import auth, register

pytestmark = pytest.mark.skipif(
    os.getenv("CONTRACTIQ_INTEGRATION") != "1", reason="needs the running stack"
)


async def _org_ids(db: Database, *emails: str) -> list[uuid.UUID]:
    async with db.session_factory() as session:
        rows = await session.execute(select(User.organization_id).where(User.email.in_(emails)))
        return list(rows.scalars())


async def test_unfiltered_queries_only_see_the_bound_tenant(api, cleanup) -> None:
    _, email_a = register(api, cleanup, "RLS A")
    _, email_b = register(api, cleanup, "RLS B")
    db = Database(Settings())
    try:
        org_a, org_b = await _org_ids(db, email_a, email_b)
        async with db.session_factory() as session:
            await bind_tenant(session, org_a)
            # No WHERE organization_id — RLS must still keep B's rows out.
            orgs = set((await session.execute(select(User.organization_id))).scalars())
            assert orgs == {org_a}
            visible = set((await session.execute(select(Organization.id))).scalars())
            assert visible == {org_a}
            # Another tenant's row by primary key: simply not there.
            assert await session.get(Organization, org_b) is None
            # It survives a commit: the next transaction is bound again.
            await session.commit()
            count = await session.scalar(select(func.count()).select_from(User))
            assert count == 1
    finally:
        await db.dispose()


async def test_a_bound_session_cannot_write_into_another_tenant(api, cleanup) -> None:
    _, email_a = register(api, cleanup, "RLS write A")
    _, email_b = register(api, cleanup, "RLS write B")
    db = Database(Settings())
    try:
        org_a, org_b = await _org_ids(db, email_a, email_b)
        async with db.session_factory() as session:
            await bind_tenant(session, org_a)
            session.add(
                User(
                    organization_id=org_b,
                    email=f"intruder-{uuid.uuid4().hex[:8]}@contractiq.test",
                    full_name="Intruder",
                    password_hash="x",
                )
            )
            with pytest.raises((DBAPIError, ProgrammingError), match="row-level security"):
                await session.flush()
    finally:
        await db.dispose()


async def test_the_tenant_role_without_a_tenant_sees_nothing(api, cleanup) -> None:
    register(api, cleanup, "RLS fail closed")
    db = Database(Settings())
    try:
        async with db.session_factory() as session:
            await session.execute(text("SET LOCAL ROLE app_tenant"))
            assert await session.scalar(select(func.count()).select_from(User)) == 0
    finally:
        await db.dispose()


async def test_every_tenant_table_is_protected() -> None:
    """A table with organization_id must either have a tenant policy
    (migration 7c1d4e2a9b30) or be out of the tenant role's reach."""
    db = Database(Settings())
    try:
        async with db.engine.connect() as conn:
            tables = await conn.run_sync(
                lambda sync: [
                    name
                    for name in inspect(sync).get_table_names()
                    if any(c["name"] == "organization_id" for c in inspect(sync).get_columns(name))
                ]
            )
            protected = set(
                (
                    await conn.execute(
                        text(
                            "SELECT c.relname FROM pg_class c "
                            "JOIN pg_policy p ON p.polrelid = c.oid "
                            "WHERE c.relrowsecurity AND p.polname = 'tenant_isolation'"
                        )
                    )
                ).scalars()
            )
            # Operator tables (platform_audit_logs, Phase 18) reference an
            # organization without belonging to one: the tenant role must
            # then have no access to them at all.
            unreachable = set(
                (
                    await conn.execute(
                        text(
                            "SELECT c.relname FROM pg_class c "
                            "WHERE c.relkind = 'r' AND NOT has_table_privilege("
                            "'app_tenant', c.oid, 'SELECT, INSERT, UPDATE, DELETE')"
                        )
                    )
                ).scalars()
            )
        assert tables, "no tenant tables found"
        assert set(tables) <= protected | unreachable, set(tables) - protected - unreachable
    finally:
        await db.dispose()


def test_api_requests_are_bound_to_their_tenant(api, cleanup) -> None:
    """End to end through the API: each company's admin lists only its own
    users, now enforced by the database as well as the repository."""
    tokens_a, email_a = register(api, cleanup, "RLS api A")
    tokens_b, email_b = register(api, cleanup, "RLS api B")
    for tokens, own, other in ((tokens_a, email_a, email_b), (tokens_b, email_b, email_a)):
        response = api.get("/api/v1/users", headers=auth(tokens))
        assert response.status_code == 200, response.text
        emails = {u["email"] for u in response.json()["data"]["items"]}
        assert own in emails and other not in emails
