"""
Portfolio-level summaries across many contracts.

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
    "/contracts/portfolio-summary",
    summary="Summarize obligations across a set of contracts",
    status_code=501,
)
async def post_contracts_portfolio_summary() -> None:
    raise NotImplementedYetError("Summarize obligations across a set of contracts", PHASE)
