"""
Background processing jobs.

Implementation lands in Phase 3. The routes are registered now so the
API contract is visible in OpenAPI and the frontend can integrate against it.
Route handlers stay thin: validation in schemas, logic in services.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.exceptions import NotImplementedYetError

router = APIRouter(tags=["jobs"])
PHASE = 3


@router.get(
    "/jobs/{job_id}", summary="Get a processing job's status and stage timings", status_code=501
)
async def get_jobs_job_id(job_id: str) -> None:
    raise NotImplementedYetError("Get a processing job's status and stage timings", PHASE)
