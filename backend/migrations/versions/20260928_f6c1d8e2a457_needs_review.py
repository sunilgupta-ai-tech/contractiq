"""documents.needs_review

Phase 21. Set by the worker when a document's recovered text may be
unreliable (weak OCR that could not be transcribed, scanned pages with no
text, a damaged PDF read by the fallback parser); cleared when a person
marks it reviewed. Indexed per tenant for the library's "Needs review"
filter.

Revision ID: f6c1d8e2a457
Revises: e5b9c2d7f341
Create Date: 2026-09-28 14:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f6c1d8e2a457"
down_revision: str | None = "e5b9c2d7f341"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index(
        "ix_documents_org_needs_review",
        "documents",
        ["organization_id"],
        postgresql_where=sa.text("needs_review"),
    )


def downgrade() -> None:
    op.drop_index("ix_documents_org_needs_review", table_name="documents")
    op.drop_column("documents", "needs_review")
