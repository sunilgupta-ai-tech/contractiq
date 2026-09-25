"""
Contract upload and lifecycle. Uploads are validated (type, size, magic bytes), stored
via ObjectStorage, and enqueued — never processed inline.

Route handlers stay thin: validation in schemas, logic in DocumentService.
The RBAC dependency is declared first on every route so unauthorized calls
are rejected before a database session is opened.
"""

from __future__ import annotations

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
)
from app.db.models import ContractType, DocumentStatus
from app.schemas.common import ApiResponse, Page
from app.schemas.document import DocumentDetail, DocumentOut, DocumentStatusOut, UploadResult
from app.services.document_service import (
    UploadMetadata,
    clean_filename,
    read_limited,
    validate_pdf,
)

router = APIRouter(tags=["documents"])


@router.post(
    "/documents/upload",
    summary="Upload a contract PDF (async processing)",
    response_model=ApiResponse[UploadResult],
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_document(
    user: DocumentUploaderDep,
    service: DocumentServiceDep,
    settings: SettingsDep,
    meta: RequestMetaDep,
    file: Annotated[UploadFile, File(description="Contract PDF")],
    title: Annotated[str | None, Form(max_length=300)] = None,
    contract_type: Annotated[ContractType | None, Form()] = None,
    counterparty: Annotated[str | None, Form(max_length=300)] = None,
    document_id: Annotated[
        uuid.UUID | None, Form(description="Upload as a new version of this document")
    ] = None,
    version_label: Annotated[str | None, Form(max_length=50)] = None,
) -> ApiResponse[UploadResult]:
    """Returns 202: the document is stored and queued; poll
    `/documents/{id}/status` for processing progress."""
    filename = clean_filename(file.filename)
    data = await read_limited(file, settings.max_upload_size_bytes)
    validate_pdf(filename, file.content_type, data)
    result = await service.upload(
        data=data,
        filename=filename,
        metadata=UploadMetadata(
            title=title or None,
            contract_type=contract_type,
            counterparty=counterparty or None,
            document_id=document_id,
            version_label=version_label or None,
        ),
        actor_id=user.user_id,
        meta=meta,
    )
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
    status_filter: Annotated[DocumentStatus | None, Query(alias="status")] = None,
    contract_type: Annotated[ContractType | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=200, description="Search title/counterparty")] = None,
) -> ApiResponse[Page[DocumentOut]]:
    return ApiResponse(
        data=await service.list(
            offset=offset,
            limit=limit,
            status=status_filter,
            contract_type=contract_type,
            search=q,
        )
    )


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
