"""one live copy of a file per organization

Phase 19. A partial unique index on (organization_id, sha256) for versions
that did not fail. The application checks for duplicates before storing a
file; this index is what makes the check hold when the same file is
uploaded twice at the same moment. It is per organization, so two
organizations may hold the same file, and nothing about one is ever
visible to the other.

Revision ID: d4a8e1f6b213
Revises: c7e2b8f4a915
Create Date: 2026-09-27 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4a8e1f6b213"
down_revision: str | None = "c7e2b8f4a915"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_document_versions_org_sha256_live",
        "document_versions",
        ["organization_id", "sha256"],
        unique=True,
        postgresql_where=sa.text("status <> 'FAILED'"),
    )


def downgrade() -> None:
    op.drop_index("uq_document_versions_org_sha256_live", table_name="document_versions")
