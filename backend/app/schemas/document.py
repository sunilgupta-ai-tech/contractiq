"""Request/response schemas for documents, versions and processing jobs."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.db.models import ContractType, DocumentStatus, JobStatus, JobType


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
    created_at: datetime


class DocumentOut(BaseModel):
    """List view: the document plus its most recent version."""

    id: uuid.UUID
    title: str
    contract_type: ContractType
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
