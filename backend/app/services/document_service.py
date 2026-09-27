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

import asyncio
import hashlib
import re
import tempfile
import unicodedata
import uuid
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING

from fastapi import UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ConflictError,
    DuplicateDocumentError,
    FileTooLargeError,
    ForbiddenError,
    InvalidFileError,
    NotFoundError,
    ServiceUnavailableError,
)
from app.core.logging import get_logger
from app.core.security import Permission
from app.db.models import (
    ContractType,
    Document,
    DocumentGrant,
    DocumentStatus,
    DocumentVersion,
    DocumentVisibility,
    FileType,
    JobStatus,
    JobType,
    ProcessingJob,
    Role,
    User,
)
from app.db.repositories.document_repository import (
    DocumentAccess,
    DocumentRepository,
    DocumentSort,
    DocumentVersionRepository,
    JobRepository,
)
from app.db.repositories.role_repository import RoleRepository
from app.db.repositories.user_repository import UserRepository
from app.document_processing.formats import (
    SUPPORTED_HINT,
    UploadFormat,
    detect_format,
    format_for_storage_key,
)
from app.queue import enqueue_document_processing
from app.schemas.common import Page
from app.schemas.document import (
    AccessGrantOut,
    DirectoryOut,
    DirectoryRole,
    DirectoryUser,
    DocumentAccessOut,
    DocumentDetail,
    DocumentFacets,
    DocumentOut,
    DocumentStatusOut,
    DocumentVersionOut,
    JobOut,
    UpdateDocumentAccessRequest,
    UploadResult,
)
from app.services.audit_service import RequestMeta, record_audit
from app.services.plans import ensure_can_upload
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
# cannot influence where the file lands (original.<ext> since Phase 16).
STORED_FILENAME = "original.pdf"
# Declared types that contradict every accepted format (an HTML page, a
# script) are refused outright; anything else is decided by the content.
_REJECTED_MIME_PREFIXES = ("text/html", "application/javascript", "text/javascript")
_READ_CHUNK = 1024 * 1024


# --- Validation (pure functions, unit-tested) ------------------------------------


@dataclass
class SpooledUpload:
    """An upload written to a temporary file (Phase 21): its path, size and
    SHA-256, computed while streaming, so the API never holds the whole file
    in memory. Delete it with `discard()` when done."""

    path: Path
    size: int
    sha256: str

    def discard(self) -> None:
        self.path.unlink(missing_ok=True)


async def spool_upload(upload: UploadFile, max_bytes: int) -> SpooledUpload:
    """Stream the upload to a temporary file, hashing as it goes, and stop
    as soon as it exceeds the limit."""
    digest = hashlib.sha256()
    size = 0
    handle = tempfile.NamedTemporaryFile(prefix="upload-", delete=False)  # noqa: SIM115
    path = Path(handle.name)
    try:
        with handle:
            while chunk := await upload.read(_READ_CHUNK):
                size += len(chunk)
                if size > max_bytes:
                    raise FileTooLargeError(
                        f"The file exceeds the {max_bytes // (1024 * 1024)} MB limit.",
                        details={"max_bytes": max_bytes},
                    )
                digest.update(chunk)
                await asyncio.to_thread(handle.write, chunk)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return SpooledUpload(path=path, size=size, sha256=digest.hexdigest())


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


def validate_upload(filename: str, content_type: str | None, data: bytes | Path) -> UploadFormat:
    """Phase 16: PDF, JPG/PNG, .docx or .xlsx, recognised from the content
    (app/document_processing/formats.py). Returns the detected format."""
    declared = (content_type or "").split(";")[0].strip().lower()
    if declared.startswith(_REJECTED_MIME_PREFIXES):
        raise InvalidFileError(f"This file type is not supported. {SUPPORTED_HINT}")
    return detect_format(filename, data)


def default_title(filename: str) -> str:
    stem = re.sub(r"\.(pdf|png|jpe?g|docx|xlsx)$", "", filename, flags=re.IGNORECASE)
    return re.sub(r"[_\s]+", " ", stem).strip()[:300] or "Untitled document"


@dataclass(frozen=True)
class UploadMetadata:
    title: str | None = None
    contract_type: ContractType | None = None
    counterparty: str | None = None
    document_id: uuid.UUID | None = None  # set to upload a new version of an existing document
    version_label: str | None = None
    # Phase 20: RESTRICTED keeps a new document private to the uploader (and
    # document:read_all holders) until access is granted.
    visibility: DocumentVisibility = DocumentVisibility.ORGANIZATION


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
        file_type=document.file_type,
        visibility=document.visibility,
        needs_review=document.needs_review,
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

    def __init__(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        resources: Resources,
        *,
        access: DocumentAccess,
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.resources = resources
        self.access = access
        # Phase 20: every read goes through the caller's document access.
        self.documents = DocumentRepository(session, tenant_id, access=access)
        self.versions = DocumentVersionRepository(session, tenant_id, access=access)
        self.jobs = JobRepository(session, tenant_id)

    async def upload(
        self,
        *,
        data: bytes | SpooledUpload,
        filename: str,
        metadata: UploadMetadata,
        actor_id: uuid.UUID,
        meta: RequestMeta,
        upload_format: UploadFormat | None = None,
    ) -> UploadResult:
        fmt = upload_format or format_for_storage_key(STORED_FILENAME)
        size = data.size if isinstance(data, SpooledUpload) else len(data)
        # Duplicates first (Phase 19): a copy of an existing file is not
        # stored, processed or embedded again, and must not be reported as
        # a plan limit either.
        sha256 = (
            data.sha256 if isinstance(data, SpooledUpload) else hashlib.sha256(data).hexdigest()
        )
        await self._reject_duplicate(sha256)
        await ensure_can_upload(
            self.session,
            self.tenant_id,
            new_document=metadata.document_id is None,
            size_bytes=size,
        )

        if metadata.document_id is not None:
            document = await self.documents.get_with_versions(metadata.document_id)
            if document.file_type is not fmt.file_type:
                # One document is one kind of file: comparing a Word v1 with
                # an Excel v2 would be meaningless.
                raise InvalidFileError(
                    f"A new version must be the same kind of file as the document "
                    f"({document.file_type.value.title()})."
                )
            version_number = max((v.version_number for v in document.versions), default=0) + 1
        else:
            document = await self.documents.add(
                Document(
                    title=(metadata.title or default_title(filename)).strip()[:300],
                    contract_type=metadata.contract_type or ContractType.OTHER,
                    counterparty=(metadata.counterparty or None),
                    file_type=fmt.file_type,
                    uploaded_by_id=actor_id,
                    visibility=metadata.visibility,
                    status=DocumentStatus.QUEUED,
                    tags=[],
                )
            )
            version_number = 1

        version_id = uuid.uuid4()
        key = build_object_key(
            str(self.tenant_id), str(document.id), str(version_id), fmt.stored_filename
        )
        try:
            if isinstance(data, SpooledUpload):
                await self.resources.storage.put_file(key, str(data.path), fmt.mime_type)
            else:
                await self.resources.storage.put(key, data, fmt.mime_type)
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
                    mime_type=fmt.mime_type,
                    size_bytes=size,
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
                    "size_bytes": size,
                    "sha256": sha256,
                },
            )
            await self.session.commit()
        except Exception as exc:
            await self.session.rollback()
            await self._delete_object_quietly(key)
            if isinstance(exc, IntegrityError):
                # The same file uploaded twice at the same moment: the
                # database's unique index lets only one through.
                await self._reject_duplicate(sha256)
                # Otherwise two versions of one document at the same moment.
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
        status: DocumentStatus | Collection[DocumentStatus] | None = None,
        contract_type: ContractType | None = None,
        file_type: FileType | None = None,
        search: str | None = None,
        sort: DocumentSort = DocumentSort.NEWEST,
        needs_review: bool | None = None,
    ) -> Page[DocumentOut]:
        rows, total = await self.documents.search(
            offset=offset,
            limit=limit,
            status=status,
            contract_type=contract_type,
            file_type=file_type,
            search=search,
            sort=sort,
            needs_review=needs_review,
        )
        return Page(
            items=[to_document_out(d) for d in rows], total=total, offset=offset, limit=limit
        )

    async def facets(
        self,
        *,
        status: DocumentStatus | Collection[DocumentStatus] | None = None,
        search: str | None = None,
    ) -> DocumentFacets:
        counts = await self.documents.file_type_counts(status=status, search=search)
        return DocumentFacets(all=sum(counts.values()), by_file_type=counts)

    async def _reject_duplicate(self, sha256: str) -> None:
        duplicate = await self.versions.find_live_duplicate(sha256)
        if duplicate is None:
            return
        if not await self.documents.is_visible(duplicate.document_id):
            # A restricted document the caller cannot see (Phase 20): the
            # file is still a duplicate, but where it lives stays private.
            raise DuplicateDocumentError()
        document = await self.documents.get_with_versions(duplicate.document_id)
        raise DuplicateDocumentError(
            details={
                # Only ever this organization's own document.
                "document_id": str(document.id),
                "document_title": document.title,
                "version_id": str(duplicate.id),
                "version_label": duplicate.label,
            }
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

    async def mark_reviewed(
        self, document_id: uuid.UUID, *, actor_id: uuid.UUID, meta: RequestMeta
    ) -> DocumentOut:
        """Phase 21: a person checked the text of a flagged document."""
        document = await self.documents.get_with_versions(document_id)
        document.needs_review = False
        record_audit(
            self.session,
            tenant_id=self.tenant_id,
            actor_user_id=actor_id,
            action="document.reviewed",
            resource_type="document",
            resource_id=document.id,
            meta=meta,
        )
        await self.session.commit()
        return to_document_out(await self.documents.get_with_versions(document_id))

    async def get_job(self, job_id: uuid.UUID) -> JobOut:
        job = await self.jobs.get(job_id)
        # Phase 20: a job reveals its document's progress; only to those
        # who may see the document.
        if job.document_version_id is not None:
            await self.versions.get(job.document_version_id)
        return JobOut.model_validate(job)

    # --- Document access (Phase 20) ---------------------------------------------------

    def _can_manage(self, document: Document, permissions: frozenset[Permission]) -> bool:
        return Permission.DOCUMENT_SHARE in permissions or (
            document.uploaded_by_id is not None and document.uploaded_by_id == self.access.user_id
        )

    async def get_access(
        self, document_id: uuid.UUID, *, permissions: frozenset[Permission]
    ) -> DocumentAccessOut:
        document = await self.documents.get(document_id)  # 404 unless visible
        grants = (
            await self.session.execute(
                select(DocumentGrant, User, Role)
                .outerjoin(User, User.id == DocumentGrant.user_id)
                .outerjoin(Role, Role.id == DocumentGrant.role_id)
                .where(DocumentGrant.document_id == document.id)
                .order_by(DocumentGrant.created_at)
            )
        ).all()
        owner = (
            await self.session.get(User, document.uploaded_by_id)
            if document.uploaded_by_id
            else None
        )
        return DocumentAccessOut(
            visibility=document.visibility,
            owner_id=document.uploaded_by_id,
            owner_name=owner.full_name if owner else None,
            grants=[
                AccessGrantOut(kind="user", id=user.id, name=user.full_name, email=user.email)
                if user is not None
                else AccessGrantOut(kind="role", id=role.id, name=role.name)
                for _, user, role in grants
            ],
            can_manage=self._can_manage(document, permissions),
        )

    async def set_access(
        self,
        document_id: uuid.UUID,
        data: UpdateDocumentAccessRequest,
        *,
        permissions: frozenset[Permission],
        actor_id: uuid.UUID,
        meta: RequestMeta,
    ) -> DocumentAccessOut:
        document = await self.documents.get(document_id)
        if not self._can_manage(document, permissions):
            raise ForbiddenError("You cannot change who can see this document.")
        user_ids, role_ids = set(data.user_ids), set(data.role_ids)
        if data.visibility is DocumentVisibility.ORGANIZATION:
            user_ids, role_ids = set(), set()
        # Only people and roles of this organization (RLS agrees).
        users = UserRepository(self.session, self.tenant_id)
        if await users.count_ids(list(user_ids)) != len(user_ids):
            raise NotFoundError("One or more of the selected users were not found.")
        roles = RoleRepository(self.session, self.tenant_id)
        for role_id in role_ids:
            await roles.get(role_id)

        document.visibility = data.visibility
        await self.session.execute(
            delete(DocumentGrant).where(DocumentGrant.document_id == document.id)
        )
        for user_id in user_ids:
            self.session.add(
                DocumentGrant(
                    organization_id=self.tenant_id,
                    document_id=document.id,
                    user_id=user_id,
                    granted_by_id=actor_id,
                )
            )
        for role_id in role_ids:
            self.session.add(
                DocumentGrant(
                    organization_id=self.tenant_id,
                    document_id=document.id,
                    role_id=role_id,
                    granted_by_id=actor_id,
                )
            )
        record_audit(
            self.session,
            tenant_id=self.tenant_id,
            actor_user_id=actor_id,
            action="document.access",
            resource_type="document",
            resource_id=document.id,
            meta=meta,
            metadata={
                "visibility": data.visibility.value,
                "users": len(user_ids),
                "roles": len(role_ids),
            },
        )
        await self.session.commit()
        return await self.get_access(document.id, permissions=permissions)

    async def directory(self) -> DirectoryOut:
        """Active colleagues and roles, to share a document with."""
        users = (
            await self.session.execute(
                select(User)
                .where(User.organization_id == self.tenant_id, User.is_active.is_(True))
                .order_by(func.lower(User.full_name))
            )
        ).scalars()
        roles = await RoleRepository(self.session, self.tenant_id).list()
        return DirectoryOut(
            users=[DirectoryUser(id=u.id, full_name=u.full_name, email=u.email) for u in users],
            roles=[DirectoryRole(id=r.id, name=r.name) for r in roles],
        )

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
