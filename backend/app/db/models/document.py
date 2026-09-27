"""
Contracts and their versions.

A `Document` is the logical contract ("MSA with Acme"); each upload of it
is a `DocumentVersion` (v1, v2, amendment). Chunks in Qdrant reference the
version ID, which makes version-to-version comparison and version filters
straightforward.
"""

from __future__ import annotations

import uuid
from datetime import date
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.db.models.base import TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.db.models.job import ProcessingJob


class DocumentStatus(StrEnum):
    """Pipeline states, in order. The frontend renders these as a stepper."""

    UPLOADED = "UPLOADED"
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    OCR_PROCESSING = "OCR_PROCESSING"
    CHUNKING = "CHUNKING"
    EMBEDDING = "EMBEDDING"
    INDEXING = "INDEXING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class FileType(StrEnum):
    """Document family shown in the Documents library tabs (Phase 15). A
    scanned PDF is still PDF; `DocumentVersion.is_scanned` tells them apart."""

    PDF = "PDF"
    IMAGE = "IMAGE"
    WORD = "WORD"
    EXCEL = "EXCEL"


class DocumentVisibility(StrEnum):
    """Who in the organization may see a document (Phase 20)."""

    ORGANIZATION = "ORGANIZATION"  # everyone with document:read
    RESTRICTED = "RESTRICTED"  # uploader, granted users/roles, document:read_all


class ContractType(StrEnum):
    MSA = "MSA"
    NDA = "NDA"
    SOW = "SOW"
    SLA = "SLA"
    DPA = "DPA"
    LEASE = "LEASE"
    EMPLOYMENT = "EMPLOYMENT"
    VENDOR = "VENDOR"
    AMENDMENT = "AMENDMENT"
    OTHER = "OTHER"


class Document(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "documents"

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    contract_type: Mapped[ContractType] = mapped_column(
        Enum(ContractType, name="contract_type"), default=ContractType.OTHER, nullable=False
    )
    counterparty: Mapped[str | None] = mapped_column(String(300))
    file_type: Mapped[FileType] = mapped_column(
        Enum(FileType, name="file_type"),
        default=FileType.PDF,
        server_default=FileType.PDF.value,
        nullable=False,
    )
    effective_date: Mapped[date | None] = mapped_column(Date)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, name="document_status"),
        default=DocumentStatus.UPLOADED,
        nullable=False,
        index=True,
    )
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    tags: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    visibility: Mapped[DocumentVisibility] = mapped_column(
        Enum(DocumentVisibility, name="document_visibility"),
        default=DocumentVisibility.ORGANIZATION,
        server_default=DocumentVisibility.ORGANIZATION.value,
        nullable=False,
    )

    versions: Mapped[list[DocumentVersion]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentVersion.version_number",
    )


class DocumentVersion(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version_number"),
        # Phase 19: one live copy of the same bytes per organization. Failed
        # versions are left out, so a file that failed can be uploaded again.
        Index(
            "uq_document_versions_org_sha256_live",
            "organization_id",
            "sha256",
            unique=True,
            postgresql_where=text("status <> 'FAILED'"),
        ),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(50), nullable=False)  # "v1", "Amendment 2"
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1000), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    page_count: Mapped[int | None] = mapped_column(Integer)
    chunk_count: Mapped[int | None] = mapped_column(Integer)
    is_scanned: Mapped[bool | None] = mapped_column()
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, name="document_status"),
        default=DocumentStatus.UPLOADED,
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    extraction_metadata: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, nullable=False
    )

    document: Mapped[Document] = relationship(back_populates="versions")

    @property
    def injection_flags(self) -> int:
        """Passages that read like instructions to an AI (Phase 20 ingest scan)."""
        found = (self.extraction_metadata or {}).get("injection") or {}
        return int(found.get("chunks", 0))

    jobs: Mapped[list[ProcessingJob]] = relationship(back_populates="document_version")


class DocumentGrant(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """Access to a RESTRICTED document for one user or one role (Phase 20).
    Exactly one of `user_id` / `role_id` is set."""

    __tablename__ = "document_grants"
    __table_args__ = (
        CheckConstraint("num_nonnulls(user_id, role_id) = 1", name="one_principal"),
        Index(
            "uq_document_grants_user",
            "document_id",
            "user_id",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
        ),
        Index(
            "uq_document_grants_role",
            "document_id",
            "role_id",
            unique=True,
            postgresql_where=text("role_id IS NOT NULL"),
        ),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    role_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE")
    )
    granted_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
