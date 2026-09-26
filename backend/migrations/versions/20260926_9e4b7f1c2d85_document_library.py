"""document library: file type and indexes for large libraries

Phase 15. Adds `documents.file_type` (every existing document is a PDF) and
the indexes the Documents library needs to stay fast at 10,000+ documents
per organization: per-tenant type filtering and recency ordering, and
trigram indexes so "contains" search on titles and file names can use an
index instead of scanning every row.

Revision ID: 9e4b7f1c2d85
Revises: 7c1d4e2a9b30
Create Date: 2026-09-26 15:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "9e4b7f1c2d85"
down_revision: str | None = "7c1d4e2a9b30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

file_type = postgresql.ENUM("PDF", "IMAGE", "WORD", "EXCEL", name="file_type")


def upgrade() -> None:
    file_type.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "documents",
        sa.Column(
            "file_type",
            postgresql.ENUM(name="file_type", create_type=False),
            nullable=False,
            server_default="PDF",
        ),
    )
    op.create_index(
        "ix_documents_org_file_type_updated",
        "documents",
        ["organization_id", "file_type", sa.text("updated_at DESC")],
    )
    op.create_index(
        "ix_documents_org_updated", "documents", ["organization_id", sa.text("updated_at DESC")]
    )

    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_index(
        "ix_documents_title_trgm",
        "documents",
        ["title"],
        postgresql_using="gin",
        postgresql_ops={"title": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_document_versions_filename_trgm",
        "document_versions",
        ["original_filename"],
        postgresql_using="gin",
        postgresql_ops={"original_filename": "gin_trgm_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_document_versions_filename_trgm", table_name="document_versions")
    op.drop_index("ix_documents_title_trgm", table_name="documents")
    op.drop_index("ix_documents_org_updated", table_name="documents")
    op.drop_index("ix_documents_org_file_type_updated", table_name="documents")
    op.drop_column("documents", "file_type")
    file_type.drop(op.get_bind(), checkfirst=True)
    # pg_trgm is left installed: other objects may depend on it.
