"""
Contract upload and lifecycle. Uploads are validated (type, size, magic bytes), stored
via ObjectStorage, and enqueued — never processed inline.

Route handlers stay thin: validation in schemas, logic in DocumentService.
The RBAC dependency is declared first on every route so unauthorized calls
are rejected before a database session is opened.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, Query, Response, UploadFile, status

from app.core.dependencies import (
    DocumentDeleterDep,
    DocumentReaderDep,
    DocumentServiceDep,
    DocumentUploaderDep,
    RequestMetaDep,
    SettingsDep,
    UploadRateLimitDep,
)
from app.db.models import ContractType, DocumentStatus, DocumentVisibility, FileType
from app.db.repositories.document_repository import DocumentSort
from app.schemas.common import ApiResponse, Page
from app.schemas.document import (
    DirectoryOut,
    DocumentAccessOut,
    DocumentDetail,
    DocumentFacets,
    DocumentOut,
    DocumentStatusOut,
    UpdateDocumentAccessRequest,
    UploadResult,
)
from app.services.document_service import (
    UploadMetadata,
    clean_filename,
    spool_upload,
    validate_upload,
)

router = APIRouter(tags=["documents"])


@router.post(
    "/documents/upload",
    summary="Upload a document: PDF, JPG/PNG, Word (.docx) or Excel (.xlsx)",
    response_model=ApiResponse[UploadResult],
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_document(
    user: DocumentUploaderDep,
    _limit: UploadRateLimitDep,
    service: DocumentServiceDep,
    settings: SettingsDep,
    meta: RequestMetaDep,
    file: Annotated[UploadFile, File(description="PDF, JPG, PNG, .docx or .xlsx")],
    title: Annotated[str | None, Form(max_length=300)] = None,
    contract_type: Annotated[ContractType | None, Form()] = None,
    counterparty: Annotated[str | None, Form(max_length=300)] = None,
    document_id: Annotated[
        uuid.UUID | None, Form(description="Upload as a new version of this document")
    ] = None,
    version_label: Annotated[str | None, Form(max_length=50)] = None,
    visibility: Annotated[
        DocumentVisibility,
        Form(description="RESTRICTED keeps a new document private to you until you share it"),
    ] = DocumentVisibility.ORGANIZATION,
) -> ApiResponse[UploadResult]:
    """Returns 202: the document is stored and queued; poll
    `/documents/{id}/status` for processing progress."""
    filename = clean_filename(file.filename)
    # Phase 21: streamed to a temporary file (hashed on the way), never held
    # whole in memory; removed once stored.
    spooled = await spool_upload(file, settings.max_upload_size_bytes)
    try:
        upload_format = await asyncio.to_thread(
            validate_upload, filename, file.content_type, spooled.path
        )
        result = await service.upload(
            data=spooled,
            filename=filename,
            upload_format=upload_format,
            metadata=UploadMetadata(
                title=title or None,
                contract_type=contract_type,
                counterparty=counterparty or None,
                document_id=document_id,
                version_label=version_label or None,
                visibility=visibility,
            ),
            actor_id=user.user_id,
            meta=meta,
        )
    finally:
        spooled.discard()
    return ApiResponse(data=result)


@router.get(
    "/documents",
    summary="List the organization's documents",
    response_model=ApiResponse[Page[DocumentOut]],
)
async def list_documents(
    _: DocumentReaderDep,
    service: DocumentServiceDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    status_filter: Annotated[
        list[DocumentStatus] | None,
        Query(alias="status", description="Repeat to match any of several statuses"),
    ] = None,
    contract_type: Annotated[ContractType | None, Query()] = None,
    file_type: Annotated[FileType | None, Query(description="PDF, IMAGE, WORD or EXCEL")] = None,
    q: Annotated[
        str | None, Query(max_length=200, description="Search title, counterparty, file name")
    ] = None,
    sort: Annotated[DocumentSort, Query()] = DocumentSort.NEWEST,
    needs_review: Annotated[
        bool | None, Query(description="Only documents flagged for review (Phase 21)")
    ] = None,
) -> ApiResponse[Page[DocumentOut]]:
    return ApiResponse(
        data=await service.list(
            offset=offset,
            limit=limit,
            status=status_filter,
            contract_type=contract_type,
            file_type=file_type,
            search=q,
            sort=sort,
            needs_review=needs_review,
        )
    )


# Declared before /documents/{document_id} so "facets" is not read as an id.
@router.get(
    "/documents/facets",
    summary="Document counts per file type (library tabs)",
    response_model=ApiResponse[DocumentFacets],
)
async def document_facets(
    _: DocumentReaderDep,
    service: DocumentServiceDep,
    status_filter: Annotated[
        list[DocumentStatus] | None,
        Query(alias="status", description="Repeat to match any of several statuses"),
    ] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> ApiResponse[DocumentFacets]:
    return ApiResponse(data=await service.facets(status=status_filter, search=q))


# Declared before /documents/{document_id} so "directory" is not read as an id.
@router.get(
    "/documents/directory",
    summary="People and roles a document can be shared with",
    response_model=ApiResponse[DirectoryOut],
)
async def directory(_: DocumentReaderDep, service: DocumentServiceDep) -> ApiResponse[DirectoryOut]:
    return ApiResponse(data=await service.directory())


@router.get(
    "/documents/{document_id}",
    summary="Get document metadata and versions",
    response_model=ApiResponse[DocumentDetail],
)
async def get_document(
    _: DocumentReaderDep, document_id: uuid.UUID, service: DocumentServiceDep
) -> ApiResponse[DocumentDetail]:
    return ApiResponse(data=await service.get(document_id))


@router.get(
    "/documents/{document_id}/status",
    summary="Get processing status",
    response_model=ApiResponse[DocumentStatusOut],
)
async def get_document_status(
    _: DocumentReaderDep, document_id: uuid.UUID, service: DocumentServiceDep
) -> ApiResponse[DocumentStatusOut]:
    return ApiResponse(data=await service.status(document_id))


@router.delete(
    "/documents/{document_id}",
    summary="Delete a document, its files and its vectors",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_document(
    user: DocumentDeleterDep,
    document_id: uuid.UUID,
    service: DocumentServiceDep,
    meta: RequestMetaDep,
) -> Response:
    await service.delete(document_id, actor_id=user.user_id, meta=meta)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Document access (Phase 20) ---------------------------------------------------------


@router.get(
    "/documents/{document_id}/access",
    summary="Who can see a document",
    response_model=ApiResponse[DocumentAccessOut],
)
async def get_access(
    user: DocumentReaderDep, document_id: uuid.UUID, service: DocumentServiceDep
) -> ApiResponse[DocumentAccessOut]:
    return ApiResponse(data=await service.get_access(document_id, permissions=user.permissions))


@router.put(
    "/documents/{document_id}/access",
    summary="Restrict a document to chosen people and roles, or open it to everyone",
    response_model=ApiResponse[DocumentAccessOut],
)
async def set_access(
    user: DocumentReaderDep,
    document_id: uuid.UUID,
    body: UpdateDocumentAccessRequest,
    service: DocumentServiceDep,
    meta: RequestMetaDep,
) -> ApiResponse[DocumentAccessOut]:
    """Needs document:share, or being the document's uploader."""
    return ApiResponse(
        data=await service.set_access(
            document_id, body, permissions=user.permissions, actor_id=user.user_id, meta=meta
        )
    )


@router.post(
    "/documents/{document_id}/reviewed",
    summary="Mark a flagged document as checked by a person",
    response_model=ApiResponse[DocumentOut],
)
async def mark_reviewed(
    user: DocumentUploaderDep,
    document_id: uuid.UUID,
    service: DocumentServiceDep,
    meta: RequestMetaDep,
) -> ApiResponse[DocumentOut]:
    return ApiResponse(
        data=await service.mark_reviewed(document_id, actor_id=user.user_id, meta=meta)
    )
