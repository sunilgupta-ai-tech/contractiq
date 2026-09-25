"""
Contract and version comparison.

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
    "/contracts/compare", summary="Compare clauses across contracts or versions", status_code=501
)
async def post_contracts_compare() -> None:
    raise NotImplementedYetError("Compare clauses across contracts or versions", PHASE)
