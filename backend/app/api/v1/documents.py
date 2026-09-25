"""
Contract upload and lifecycle. Uploads are validated (type, size, magic bytes), stored
via ObjectStorage, and enqueued — never processed inline.

Implementation lands in Phase 3. The routes are registered now so the
API contract is visible in OpenAPI and the frontend can integrate against it.
Route handlers stay thin: validation in schemas, logic in services.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.exceptions import NotImplementedYetError

router = APIRouter(tags=["documents"])
PHASE = 3


@router.post(
    "/documents/upload", summary="Upload a contract PDF (async processing)", status_code=501
)
async def post_documents_upload() -> None:
    raise NotImplementedYetError("Upload a contract PDF (async processing)", PHASE)


@router.get("/documents", summary="List the organization's documents", status_code=501)
async def get_documents() -> None:
    raise NotImplementedYetError("List the organization's documents", PHASE)


@router.get(
    "/documents/{document_id}", summary="Get document metadata and versions", status_code=501
)
async def get_documents_document_id(document_id: str) -> None:
    raise NotImplementedYetError("Get document metadata and versions", PHASE)


@router.get("/documents/{document_id}/status", summary="Get processing status", status_code=501)
async def get_documents_document_id_status(document_id: str) -> None:
    raise NotImplementedYetError("Get processing status", PHASE)


@router.delete(
    "/documents/{document_id}",
    summary="Delete a document, its files and its vectors",
    status_code=501,
)
async def delete_documents_document_id(document_id: str) -> None:
    raise NotImplementedYetError("Delete a document, its files and its vectors", PHASE)
