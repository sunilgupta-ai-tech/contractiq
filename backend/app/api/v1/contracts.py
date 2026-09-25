"""
Contract intelligence: summaries and clause extraction.

Implementation lands in Phase 10. The routes are registered now so the
API contract is visible in OpenAPI and the frontend can integrate against it.
Route handlers stay thin: validation in schemas, logic in services.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.exceptions import NotImplementedYetError

router = APIRouter(tags=["contracts"])
PHASE = 10


@router.post(
    "/contracts/summarize",
    summary="Executive summary with cited obligations and key dates",
    status_code=501,
)
async def post_contracts_summarize() -> None:
    raise NotImplementedYetError("Executive summary with cited obligations and key dates", PHASE)


@router.post(
    "/contracts/extract-clauses",
    summary="Extract standard clauses (termination, liability, ...)",
    status_code=501,
)
async def post_contracts_extract_clauses() -> None:
    raise NotImplementedYetError("Extract standard clauses (termination, liability, ...)", PHASE)
