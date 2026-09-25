"""Background processing jobs (read-only; jobs are created by uploads)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.core.dependencies import DocumentReaderDep, DocumentServiceDep
from app.schemas.common import ApiResponse
from app.schemas.document import JobOut

router = APIRouter(tags=["jobs"])


@router.get(
    "/jobs/{job_id}",
    summary="Get a processing job's status and stage timings",
    response_model=ApiResponse[JobOut],
)
async def get_job(
    _: DocumentReaderDep, job_id: uuid.UUID, service: DocumentServiceDep
) -> ApiResponse[JobOut]:
    return ApiResponse(data=await service.get_job(job_id))
