"""document-level access: visibility and grants

Phase 20. Inside one organization, a document can be RESTRICTED to its
uploader, chosen users and chosen roles (plus holders of
document:read_all). Existing documents stay visible to the whole
organization.

Also adds the two new permissions to the built-in roles: Admin gets
document:share and document:read_all, Manager gets document:share.

Revision ID: e5b9c2d7f341
Revises: d4a8e1f6b213
Create Date: 2026-09-28 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e5b9c2d7f341"
down_revision: str | None = "d4a8e1f6b213"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE = "app_tenant"
CURRENT_TENANT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
ADMIN_ID = "00000000-0000-4000-8000-00000000a001"
MANAGER_ID = "00000000-0000-4000-8000-00000000a002"

visibility = postgresql.ENUM("ORGANIZATION", "RESTRICTED", name="document_visibility")


def _add_permissions(role_id: str, permissions: list[str]) -> None:
    for permission in permissions:
        op.execute(
            f"UPDATE roles SET permissions = permissions || '[\"{permission}\"]'::jsonb "
            f"WHERE id = '{role_id}' AND NOT permissions ? '{permission}'"
        )


def upgrade() -> None:
    visibility.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "documents",
        sa.Column(
            "visibility",
            postgresql.ENUM(name="document_visibility", create_type=False),
            nullable=False,
            server_default="ORGANIZATION",
        ),
    )

    op.create_table(
        "document_grants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
        ),
        sa.Column(
            "role_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("roles.id", ondelete="CASCADE"),
        ),
        sa.Column(
            "granted_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "num_nonnulls(user_id, role_id) = 1", name="ck_document_grants_one_principal"
        ),
    )
    op.create_index("ix_document_grants_organization_id", "document_grants", ["organization_id"])
    op.create_index("ix_document_grants_document_id", "document_grants", ["document_id"])
    op.create_index(
        "uq_document_grants_user",
        "document_grants",
        ["document_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    op.create_index(
        "uq_document_grants_role",
        "document_grants",
        ["document_id", "role_id"],
        unique=True,
        postgresql_where=sa.text("role_id IS NOT NULL"),
    )

    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON document_grants TO {ROLE}")
    op.execute("ALTER TABLE document_grants ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON document_grants TO {ROLE} "
        f"USING (organization_id = {CURRENT_TENANT}) "
        f"WITH CHECK (organization_id = {CURRENT_TENANT})"
    )

    _add_permissions(ADMIN_ID, ["document:share", "document:read_all"])
    _add_permissions(MANAGER_ID, ["document:share"])


def downgrade() -> None:
    for role_id in (ADMIN_ID, MANAGER_ID):
        op.execute(
            f"UPDATE roles SET permissions = permissions - 'document:share' - 'document:read_all' "
            f"WHERE id = '{role_id}'"
        )
    op.drop_table("document_grants")
    op.drop_column("documents", "visibility")
    visibility.drop(op.get_bind(), checkfirst=True)
