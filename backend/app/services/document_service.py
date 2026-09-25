"""
Document upload and lifecycle.

Upload: validate (extension, MIME, %PDF magic bytes, size), hash for
dedupe, store via ObjectStorage, create Document/DocumentVersion/
ProcessingJob rows, enqueue the worker job, write an audit entry. The PDF
is never parsed inline — expensive work is asynchronous.

Consistency rules, since three systems (object store, Postgres, queue) are
involved and none share a transaction:

* The file is written before the rows are committed. If the commit fails,
  the file is deleted, so no row ever points at a missing object.
* The job is enqueued only after the rows are committed, so the worker
  never receives a job ID it cannot find. If enqueueing fails, the rows are
  marked FAILED (with a user-facing reason) rather than left QUEUED forever.
* Delete removes vectors first (nothing stays retrievable), then rows, then
  files. A leftover file after a storage error is logged, never served.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING

from fastapi import UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ConflictError,
    FileTooLargeError,
    InvalidFileError,
    ServiceUnavailableError,
)
from app.core.logging import get_logger
from app.db.models import (
    ContractType,
    Document,
    DocumentStatus,
    DocumentVersion,
    JobStatus,
    JobType,
    ProcessingJob,
)
from app.db.repositories.document_repository import (
    DocumentRepository,
    DocumentVersionRepository,
    JobRepository,
)
from app.queue import enqueue_document_processing
from app.schemas.common import Page
from app.schemas.document import (
    DocumentDetail,
    DocumentOut,
    DocumentStatusOut,
    DocumentVersionOut,
    JobOut,
    UploadResult,
)
from app.services.audit_service import RequestMeta, record_audit
from app.storage import build_object_key, document_prefix
from app.vectorstore.indexing import delete_document_points

if TYPE_CHECKING:
    from app.core.resources import Resources

logger = get_logger(__name__)

PDF_MIME = "application/pdf"
# Browsers and HTTP clients label PDFs inconsistently, so the declared type
# is only a coarse filter; the magic bytes are the real check.
ACCEPTED_MIME_TYPES = frozenset({PDF_MIME, "application/x-pdf", "application/octet-stream", ""})
PDF_MAGIC = b"%PDF-"
# The object key never contains the user's filename, so a crafted name
# cannot influence where the file lands.
STORED_FILENAME = "original.pdf"
_READ_CHUNK = 1024 * 1024


# --- Validation (pure functions, unit-tested) ------------------------------------


async def read_limited(upload: UploadFile, max_bytes: int) -> bytes:
    """Read the upload in chunks and stop as soon as it exceeds the limit."""
    chunks: list[bytes] = []
    size = 0
    while chunk := await upload.read(_READ_CHUNK):
        size += len(chunk)
        if size > max_bytes:
            raise FileTooLargeError(
                f"The file exceeds the {max_bytes // (1024 * 1024)} MB limit.",
                details={"max_bytes": max_bytes},
            )
        chunks.append(chunk)
    return b"".join(chunks)


def clean_filename(raw: str | None) -> str:
    """Display name only: strip any client path, control characters and
    excess length. Never used to build a storage path."""
    name = PureWindowsPath(PurePosixPath(raw or "").name).name
    name = "".join(ch for ch in name if unicodedata.category(ch)[0] != "C").strip()
    return name[:255] or "document.pdf"


def validate_pdf(filename: str, content_type: str | None, data: bytes) -> None:
    if not filename.lower().endswith(".pdf"):
        raise InvalidFileError("Only PDF files are supported.")
    if (content_type or "").split(";")[0].strip().lower() not in ACCEPTED_MIME_TYPES:
        raise InvalidFileError("Only PDF files are supported.")
    if not data:
        raise InvalidFileError("The file is empty.")
    if not data.startswith(PDF_MAGIC):
        # Catches renamed non-PDFs (e.g. an .exe saved as contract.pdf).
        raise InvalidFileError("The file is not a valid PDF.")


def default_title(filename: str) -> str:
    stem = re.sub(r"\.pdf$", "", filename, flags=re.IGNORECASE)
    return re.sub(r"[_\s]+", " ", stem).strip()[:300] or "Untitled contract"


@dataclass(frozen=True)
class UploadMetadata:
    title: str | None = None
    contract_type: ContractType | None = None
    counterparty: str | None = None
    document_id: uuid.UUID | None = None  # set to upload a new version of an existing document
    version_label: str | None = None


# --- Response builders -----------------------------------------------------------


def _latest(document: Document) -> DocumentVersion | None:
    if not document.versions:
        return None
    return max(document.versions, key=lambda v: v.version_number)


def to_document_out(document: Document) -> DocumentOut:
    latest = _latest(document)
    return DocumentOut(
        id=document.id,
        title=document.title,
        contract_type=document.contract_type,
        counterparty=document.counterparty,
        status=document.status,
        effective_date=document.effective_date,
        expiry_date=document.expiry_date,
        tags=list(document.tags or []),
        current_version_id=document.current_version_id,
        latest_version=DocumentVersionOut.model_validate(latest) if latest else None,
        version_count=len(document.versions),
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


def to_document_detail(document: Document) -> DocumentDetail:
    return DocumentDetail(
        **to_document_out(document).model_dump(),
        versions=[DocumentVersionOut.model_validate(v) for v in document.versions],
    )


# --- Service ---------------------------------------------------------------------


class DocumentService:
    """All operations are scoped to the caller's tenant (from the signed token)."""

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID, resources: Resources) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.resources = resources
        self.documents = DocumentRepository(session, tenant_id)
        self.versions = DocumentVersionRepository(session, tenant_id)
        self.jobs = JobRepository(session, tenant_id)

    async def upload(
        self,
        *,
        data: bytes,
        filename: str,
        metadata: UploadMetadata,
        actor_id: uuid.UUID,
        meta: RequestMeta,
    ) -> UploadResult:
        sha256 = hashlib.sha256(data).hexdigest()
        duplicate = await self.versions.find_live_duplicate(sha256)
        if duplicate is not None:
            raise ConflictError(
                "This file has already been uploaded.",
                details={
                    "document_id": str(duplicate.document_id),
                    "version_id": str(duplicate.id),
                },
            )

        if metadata.document_id is not None:
            document = await self.documents.get_with_versions(metadata.document_id)
            version_number = max((v.version_number for v in document.versions), default=0) + 1
        else:
            document = await self.documents.add(
                Document(
                    title=(metadata.title or default_title(filename)).strip()[:300],
                    contract_type=metadata.contract_type or ContractType.OTHER,
                    counterparty=(metadata.counterparty or None),
                    uploaded_by_id=actor_id,
                    status=DocumentStatus.QUEUED,
                    tags=[],
                )
            )
            version_number = 1

        version_id = uuid.uuid4()
        key = build_object_key(
            str(self.tenant_id), str(document.id), str(version_id), STORED_FILENAME
        )
        try:
            await self.resources.storage.put(key, data, PDF_MIME)
        except Exception as exc:
            await self.session.rollback()
            raise ServiceUnavailableError(
                "The file could not be stored. Please try again.", internal_detail=repr(exc)
            ) from exc

        try:
            version = await self.versions.add(
                DocumentVersion(
                    id=version_id,
                    document_id=document.id,
                    version_number=version_number,
                    label=(metadata.version_label or f"v{version_number}").strip()[:50],
                    original_filename=filename,
                    storage_key=key,
                    mime_type=PDF_MIME,
                    size_bytes=len(data),
                    sha256=sha256,
                    status=DocumentStatus.QUEUED,
                    extraction_metadata={},
                )
            )
            job = await self.jobs.add(
                ProcessingJob(
                    job_type=JobType.DOCUMENT_PROCESSING,
                    status=JobStatus.PENDING,
                    document_version_id=version.id,
                    progress=0,
                    attempts=0,
                    stage_timings_ms={},
                )
            )
            job.queue_job_id = str(job.id)
            document.status = DocumentStatus.QUEUED
            record_audit(
                self.session,
                tenant_id=self.tenant_id,
                actor_user_id=actor_id,
                action="document.upload",
                resource_type="document",
                resource_id=document.id,
                meta=meta,
                metadata={
                    "version_id": str(version.id),
                    "version_number": version_number,
                    "size_bytes": len(data),
                    "sha256": sha256,
                },
            )
            await self.session.commit()
        except Exception as exc:
            await self.session.rollback()
            await self._delete_object_quietly(key)
            if isinstance(exc, IntegrityError):
                # Two versions of one document uploaded at the same moment.
                raise ConflictError(
                    "Another version of this document was uploaded at the same time. "
                    "Please try again."
                ) from exc
            raise

        try:
            await enqueue_document_processing(self.resources.queue, str(job.id))
        except Exception as exc:
            reason = "The document could not be queued for processing. Please upload it again."
            job.status, job.error_message = JobStatus.FAILED, "enqueue failed"
            version.status, version.error_message = DocumentStatus.FAILED, reason
            document.status = DocumentStatus.FAILED
            await self.session.commit()
            raise ServiceUnavailableError(reason, internal_detail=repr(exc)) from exc

        document = await self.documents.get_with_versions(document.id)
        await self.session.refresh(job)
        return UploadResult(
            document=to_document_out(document),
            version=DocumentVersionOut.model_validate(
                next(v for v in document.versions if v.id == version_id)
            ),
            job=JobOut.model_validate(job),
        )

    async def list(
        self,
        *,
        offset: int,
        limit: int,
        status: DocumentStatus | None = None,
        contract_type: ContractType | None = None,
        search: str | None = None,
    ) -> Page[DocumentOut]:
        rows, total = await self.documents.search(
            offset=offset, limit=limit, status=status, contract_type=contract_type, search=search
        )
        return Page(
            items=[to_document_out(d) for d in rows], total=total, offset=offset, limit=limit
        )

    async def get(self, document_id: uuid.UUID) -> DocumentDetail:
        return to_document_detail(await self.documents.get_with_versions(document_id))

    async def status(self, document_id: uuid.UUID) -> DocumentStatusOut:
        document = await self.documents.get_with_versions(document_id)
        latest = _latest(document)
        job = await self.jobs.latest_for_version(latest.id) if latest else None
        return DocumentStatusOut(
            document_id=document.id,
            status=document.status,
            version_id=latest.id if latest else None,
            progress=job.progress if job else 0,
            current_stage=job.current_stage if job else None,
            error_message=latest.error_message if latest else None,
            job=JobOut.model_validate(job) if job else None,
        )

    async def get_job(self, job_id: uuid.UUID) -> JobOut:
        return JobOut.model_validate(await self.jobs.get(job_id))

    async def delete(
        self, document_id: uuid.UUID, *, actor_id: uuid.UUID, meta: RequestMeta
    ) -> None:
        document = await self.documents.get_with_versions(document_id)
        version_count = len(document.versions)

        # Vectors first: once this succeeds nothing about the document can be
        # retrieved, even if a later step fails and the user retries.
        try:
            await delete_document_points(
                self.resources.qdrant,
                self.resources.settings.qdrant_collection,
                tenant_id=str(self.tenant_id),
                document_id=str(document.id),
            )
        except Exception as exc:
            raise ServiceUnavailableError(
                "The document could not be deleted right now. Please try again.",
                internal_detail=repr(exc),
            ) from exc

        await self.documents.delete_by_id(document.id)
        record_audit(
            self.session,
            tenant_id=self.tenant_id,
            actor_user_id=actor_id,
            action="document.delete",
            resource_type="document",
            resource_id=document.id,
            meta=meta,
            metadata={"versions": version_count},
        )
        await self.session.commit()

        # The whole document folder: every version's PDF plus derived files
        # (parsed.json, extracted images). Rows are already gone, so a failure
        # here leaves unreachable bytes, which are logged rather than surfaced.
        prefix = document_prefix(str(self.tenant_id), str(document.id))
        try:
            await self.resources.storage.delete_prefix(prefix)
        except Exception as exc:  # noqa: BLE001
            logger.warning("storage_delete_failed", extra={"prefix": prefix, "error": repr(exc)})

    async def _delete_object_quietly(self, key: str) -> None:
        try:
            await self.resources.storage.delete(key)
        except Exception as exc:  # noqa: BLE001 — orphaned bytes are not user-visible
            logger.warning("storage_delete_failed", extra={"key": key, "error": repr(exc)})
