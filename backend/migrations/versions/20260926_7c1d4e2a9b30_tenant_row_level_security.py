"""tenant row-level security

Phase 15: database-level tenant isolation. Sessions bound to a tenant
(app/db/tenancy.py) run as the `app_tenant` role; these policies limit that
role to rows whose `organization_id` matches the transaction's
`app.tenant_id`. Without a tenant set, no row matches (fail closed).

The role gets explicit grants on these tables only. A new tenant table must
be added here (see TENANT_TABLES and the test that checks it), otherwise a
bound session is refused access to it instead of silently seeing all rows.

Revision ID: 7c1d4e2a9b30
Revises: 06e3a984a1e5
Create Date: 2026-09-26 15:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "7c1d4e2a9b30"
down_revision: str | None = "06e3a984a1e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE = "app_tenant"
CURRENT_TENANT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"

# Every table with an organization_id column.
TENANT_TABLES = (
    "users",
    "audit_logs",
    "conversations",
    "messages",
    "documents",
    "document_versions",
    "processing_jobs",
    "evaluation_runs",
)


def upgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{ROLE}') THEN
                CREATE ROLE {ROLE} NOLOGIN NOBYPASSRLS;
            END IF;
        END
        $$;
        """
    )
    # The application's login role switches to it per transaction.
    op.execute(f"GRANT {ROLE} TO CURRENT_USER")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {ROLE}")

    for table in TENANT_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {ROLE}")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} TO {ROLE} "
            f"USING (organization_id = {CURRENT_TENANT}) "
            f"WITH CHECK (organization_id = {CURRENT_TENANT})"
        )

    # A tenant may read and rename its own organization, nothing more.
    op.execute(f"GRANT SELECT, UPDATE ON organizations TO {ROLE}")
    op.execute("ALTER TABLE organizations ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON organizations TO {ROLE} "
        f"USING (id = {CURRENT_TENANT}) WITH CHECK (id = {CURRENT_TENANT})"
    )


def downgrade() -> None:
    for table in (*TENANT_TABLES, "organizations"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON {table} FROM {ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {ROLE}")
    # The role itself is cluster-wide and may hold grants in other databases
    # (e.g. a test database), so it is left in place.
