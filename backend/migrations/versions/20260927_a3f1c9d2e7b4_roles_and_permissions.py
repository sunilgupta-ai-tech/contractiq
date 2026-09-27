"""roles and permissions: system + custom roles

Phase 17. Replaces the fixed `users.role` enum with a `roles` table:

* four system roles with fixed IDs (organization_id NULL): Admin, Manager,
  Employee, Viewer — the old ADMIN, LEGAL_MANAGER, ANALYST and VIEWER;
* custom roles per organization;
* `users.role_id` (RESTRICT: a role in use cannot be deleted).

Row-level security: a tenant session reads the system roles and its own
custom roles, and writes only its own.

Revision ID: a3f1c9d2e7b4
Revises: 9e4b7f1c2d85
Create Date: 2026-09-27 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a3f1c9d2e7b4"
down_revision: str | None = "9e4b7f1c2d85"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE = "app_tenant"
CURRENT_TENANT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"

ALL = [
    "document:read",
    "document:upload",
    "document:delete",
    "query:run",
    "analysis:run",
    "evaluation:run",
    "user:manage",
    "role:manage",
]
# (id, old enum value, name, description, permissions) — a snapshot, so this
# migration does not change if the code's defaults change later.
SYSTEM_ROLES = [
    (
        "00000000-0000-4000-8000-00000000a001",
        "ADMIN",
        "Admin",
        "Full access, including users and roles.",
        ALL,
    ),
    (
        "00000000-0000-4000-8000-00000000a002",
        "LEGAL_MANAGER",
        "Manager",
        "Manage documents (including delete), ask, analyse, evaluate.",
        ALL[:6],
    ),
    (
        "00000000-0000-4000-8000-00000000a003",
        "ANALYST",
        "Employee",
        "Upload documents, ask questions and run analysis.",
        ["document:read", "document:upload", "query:run", "analysis:run"],
    ),
    (
        "00000000-0000-4000-8000-00000000a004",
        "VIEWER",
        "Viewer",
        "Read documents and ask questions.",
        ["document:read", "query:run"],
    ),
]


def upgrade() -> None:
    op.create_table(
        "roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("description", sa.String(300), nullable=False, server_default=""),
        sa.Column(
            "permissions", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'")
        ),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("organization_id", "name", name="uq_roles_organization_id"),
    )
    op.create_index("ix_roles_organization_id", "roles", ["organization_id"])

    roles = sa.table(
        "roles",
        sa.column("id", postgresql.UUID(as_uuid=False)),
        sa.column("name", sa.String),
        sa.column("description", sa.String),
        sa.column("permissions", postgresql.JSONB),
        sa.column("is_system", sa.Boolean),
    )
    op.bulk_insert(
        roles,
        [
            {
                "id": role_id,
                "name": name,
                "description": description,
                "permissions": permissions,
                "is_system": True,
            }
            for role_id, _, name, description, permissions in SYSTEM_ROLES
        ],
    )

    op.add_column("users", sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=True))
    for role_id, old, *_ in SYSTEM_ROLES:
        op.execute(f"UPDATE users SET role_id = '{role_id}' WHERE role = '{old}'")
    op.alter_column("users", "role_id", nullable=False)
    op.create_foreign_key(
        "fk_users_role_id_roles", "users", "roles", ["role_id"], ["id"], ondelete="RESTRICT"
    )
    op.create_index("ix_users_role_id", "users", ["role_id"])
    op.drop_column("users", "role")
    op.execute("DROP TYPE IF EXISTS user_role")

    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON roles TO {ROLE}")
    op.execute("ALTER TABLE roles ENABLE ROW LEVEL SECURITY")
    # Writes (and reads) of the tenant's own roles...
    op.execute(
        f"CREATE POLICY tenant_isolation ON roles TO {ROLE} "
        f"USING (organization_id = {CURRENT_TENANT}) "
        f"WITH CHECK (organization_id = {CURRENT_TENANT})"
    )
    # ...plus read-only access to the shared system roles (policies OR).
    op.execute(
        f"CREATE POLICY system_roles_read ON roles FOR SELECT TO {ROLE} "
        "USING (organization_id IS NULL)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS system_roles_read ON roles")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON roles")
    user_role = postgresql.ENUM("ADMIN", "LEGAL_MANAGER", "ANALYST", "VIEWER", name="user_role")
    user_role.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "users",
        sa.Column(
            "role",
            postgresql.ENUM(name="user_role", create_type=False),
            nullable=False,
            server_default="VIEWER",
        ),
    )
    for role_id, old, *_ in SYSTEM_ROLES:
        op.execute(f"UPDATE users SET role = '{old}' WHERE role_id = '{role_id}'")
    op.drop_index("ix_users_role_id", table_name="users")
    op.drop_constraint("fk_users_role_id_roles", "users", type_="foreignkey")
    op.drop_column("users", "role_id")
    op.drop_table("roles")
