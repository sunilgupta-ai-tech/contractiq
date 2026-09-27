"""platform console: organization status, plans and limits; platform admins

Phase 18.

* organizations: `status` (ACTIVE / SUSPENDED, replacing `is_active`),
  suspension reason and time, `plan` and per-organization limits.
  Existing organizations move to BUSINESS with its limits.
* platform_admins and platform_audit_logs: the operator side. No grants to
  the tenant role, so no tenant session can read them.

Revision ID: c7e2b8f4a915
Revises: a3f1c9d2e7b4
Create Date: 2026-09-27 14:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c7e2b8f4a915"
down_revision: str | None = "a3f1c9d2e7b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

status_enum = postgresql.ENUM("ACTIVE", "SUSPENDED", name="organization_status")
plan_enum = postgresql.ENUM("FREE", "STARTER", "BUSINESS", "ENTERPRISE", name="organization_plan")
platform_role = postgresql.ENUM("SUPER_ADMIN", "SUPPORT", name="platform_role")


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    bind = op.get_bind()
    status_enum.create(bind, checkfirst=True)
    plan_enum.create(bind, checkfirst=True)
    platform_role.create(bind, checkfirst=True)

    op.add_column(
        "organizations",
        sa.Column(
            "status",
            postgresql.ENUM(name="organization_status", create_type=False),
            nullable=False,
            server_default="ACTIVE",
        ),
    )
    op.execute("UPDATE organizations SET status = 'SUSPENDED' WHERE is_active = false")
    op.drop_column("organizations", "is_active")
    op.create_index("ix_organizations_status", "organizations", ["status"])
    op.add_column("organizations", sa.Column("suspended_reason", sa.String(300)))
    op.add_column("organizations", sa.Column("suspended_at", sa.DateTime(timezone=True)))
    op.add_column(
        "organizations",
        sa.Column(
            "plan",
            postgresql.ENUM(name="organization_plan", create_type=False),
            nullable=False,
            server_default="FREE",
        ),
    )
    op.add_column("organizations", sa.Column("max_users", sa.Integer()))
    op.add_column("organizations", sa.Column("max_documents", sa.Integer()))
    op.add_column("organizations", sa.Column("max_storage_mb", sa.Integer()))
    # Existing organizations keep working comfortably: BUSINESS defaults.
    op.execute(
        "UPDATE organizations SET plan = 'BUSINESS', max_users = 100, "
        "max_documents = 20000, max_storage_mb = 204800"
    )

    op.create_table(
        "platform_admins",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM(name="platform_role", create_type=False),
            nullable=False,
            server_default="SUPPORT",
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    op.create_index("ix_platform_admins_email", "platform_admins", ["email"], unique=True)

    op.create_table(
        "platform_audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "actor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("platform_admins.id", ondelete="SET NULL"),
        ),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("target_type", sa.String(50)),
        sa.Column("target_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="SET NULL"),
        ),
        sa.Column("details", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("ip_address", sa.String(64)),
        *_timestamps(),
    )
    op.create_index("ix_platform_audit_logs_actor_id", "platform_audit_logs", ["actor_id"])
    op.create_index("ix_platform_audit_logs_action", "platform_audit_logs", ["action"])
    op.create_index(
        "ix_platform_audit_logs_organization_id", "platform_audit_logs", ["organization_id"]
    )
    op.create_index("ix_platform_audit_logs_created_at", "platform_audit_logs", ["created_at"])


def downgrade() -> None:
    op.drop_table("platform_audit_logs")
    op.drop_table("platform_admins")
    op.add_column(
        "organizations",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.execute("UPDATE organizations SET is_active = (status = 'ACTIVE')")
    op.drop_index("ix_organizations_status", table_name="organizations")
    for column in (
        "status",
        "suspended_reason",
        "suspended_at",
        "plan",
        "max_users",
        "max_documents",
        "max_storage_mb",
    ):
        op.drop_column("organizations", column)
    bind = op.get_bind()
    platform_role.drop(bind, checkfirst=True)
    plan_enum.drop(bind, checkfirst=True)
    status_enum.drop(bind, checkfirst=True)
