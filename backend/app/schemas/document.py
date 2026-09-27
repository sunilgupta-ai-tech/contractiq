"""Request/response schemas for documents, versions and processing jobs."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import (
    ContractType,
    DocumentStatus,
    DocumentVisibility,
    FileType,
    JobStatus,
    JobType,
)


class DocumentVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version_number: int
    label: str
    original_filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    page_count: int | None
    is_scanned: bool | None
    status: DocumentStatus
    error_message: str | None
    # Phase 20: passages that read like instructions to an AI. They are
    # treated as data regardless; the count is shown so people know.
    injection_flags: int = 0
    review_reasons: list[str] = []
    created_at: datetime


class DocumentOut(BaseModel):
    """List view: the document plus its most recent version."""

    id: uuid.UUID
    title: str
    contract_type: ContractType
    file_type: FileType
    visibility: DocumentVisibility
    needs_review: bool
    counterparty: str | None
    status: DocumentStatus
    effective_date: date | None
    expiry_date: date | None
    tags: list[str]
    current_version_id: uuid.UUID | None
    latest_version: DocumentVersionOut | None
    version_count: int
    created_at: datetime
    updated_at: datetime


class DocumentDetail(DocumentOut):
    versions: list[DocumentVersionOut]


class DocumentFacets(BaseModel):
    """Counts for the library tabs: `all` plus one per file type, under the
    same status/search filters as the list."""

    all: int
    by_file_type: dict[FileType, int]


class AccessGrantOut(BaseModel):
    kind: Literal["user", "role"]
    id: uuid.UUID
    name: str
    email: str | None = None


class DocumentAccessOut(BaseModel):
    """Who can see a document (Phase 20)."""

    visibility: DocumentVisibility
    owner_id: uuid.UUID | None
    owner_name: str | None
    grants: list[AccessGrantOut]
    can_manage: bool


class UpdateDocumentAccessRequest(BaseModel):
    """Replace a document's access. With ORGANIZATION the grants are cleared."""

    visibility: DocumentVisibility
    user_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    role_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)


class DirectoryUser(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str


class DirectoryRole(BaseModel):
    id: uuid.UUID
    name: str


class DirectoryOut(BaseModel):
    """People and roles a document can be shared with."""

    users: list[DirectoryUser]
    roles: list[DirectoryRole]


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_type: JobType
    status: JobStatus
    document_version_id: uuid.UUID | None
    current_stage: str | None
    progress: int
    attempts: int
    error_message: str | None
    stage_timings_ms: dict[str, float]
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class DocumentStatusOut(BaseModel):
    """Polled by the UI while a document is processing."""

    document_id: uuid.UUID
    status: DocumentStatus
    version_id: uuid.UUID | None
    progress: int
    current_stage: str | None
    error_message: str | None
    job: JobOut | None


class UploadResult(BaseModel):
    document: DocumentOut
    version: DocumentVersionOut
    job: JobOut
