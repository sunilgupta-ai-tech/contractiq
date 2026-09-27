"""SaaS: AI usage counters and limits, invitations, organization deletion

Phase 22.

* organization_status gains DELETING (data erased in the background).
* organizations: max_ai_queries_month, max_ai_tokens_month. Existing
  organizations get the BUSINESS values they are on.
* usage_counters: AI usage per organization per month (durable, for limits
  and billing).
* invitations: invite links (token stored hashed), one use, expiring.

Both new tables are tenant tables under row-level security.

Revision ID: a1b2c3d4e5f6
Revises: f6c1d8e2a457
Create Date: 2026-09-29 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "f6c1d8e2a457"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE = "app_tenant"
CURRENT_TENANT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def _tenant_table(name: str) -> None:
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {name} TO {ROLE}")
    op.execute(f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {name} TO {ROLE} "
        f"USING (organization_id = {CURRENT_TENANT}) "
        f"WITH CHECK (organization_id = {CURRENT_TENANT})"
    )


def _org_fk() -> sa.Column:
    return sa.Column(
        "organization_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )


def upgrade() -> None:
    # ADD VALUE cannot run inside a transaction block on older servers.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE organization_status ADD VALUE IF NOT EXISTS 'DELETING'")

    op.add_column("organizations", sa.Column("max_ai_queries_month", sa.Integer()))
    op.add_column("organizations", sa.Column("max_ai_tokens_month", sa.BigInteger()))
    op.execute(
        "UPDATE organizations SET max_ai_queries_month = 20000, max_ai_tokens_month = 40000000 "
        "WHERE plan = 'BUSINESS'"
    )

    op.create_table(
        "usage_counters",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _org_fk(),
        sa.Column("period", sa.String(7), nullable=False),
        sa.Column("queries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("prompt_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("embedding_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("model_calls", sa.Integer(), nullable=False, server_default="0"),
        *_timestamps(),
        sa.UniqueConstraint("organization_id", "period", name="uq_usage_counters_organization_id"),
    )
    op.create_index("ix_usage_counters_organization_id", "usage_counters", ["organization_id"])
    _tenant_table("usage_counters")

    op.create_table(
        "invitations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _org_fk(),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column(
            "role_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("roles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column(
            "invited_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.UniqueConstraint("token_hash", name="uq_invitations_token_hash"),
    )
    op.create_index("ix_invitations_organization_id", "invitations", ["organization_id"])
    op.create_index("ix_invitations_email", "invitations", ["email"])
    _tenant_table("invitations")


def downgrade() -> None:
    op.drop_table("invitations")
    op.drop_table("usage_counters")
    op.drop_column("organizations", "max_ai_tokens_month")
    op.drop_column("organizations", "max_ai_queries_month")
    # Enum values cannot be dropped in PostgreSQL; DELETING stays defined.
