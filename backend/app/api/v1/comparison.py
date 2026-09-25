"""
Contract and version comparison (Phase 10).

Handlers stay thin: validation in schemas, logic in ComparisonService.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.dependencies import AnalystDep, ComparisonServiceDep
from app.schemas.analysis import CompareRequest, CompareResponse
from app.schemas.common import ApiResponse

router = APIRouter(tags=["contracts"])


@router.post(
    "/contracts/compare",
    summary="Compare clauses across contracts or versions",
    response_model=ApiResponse[CompareResponse],
)
async def post_contracts_compare(
    _: AnalystDep, body: CompareRequest, service: ComparisonServiceDep
) -> ApiResponse[CompareResponse]:
    """Clauses aligned by topic (so renumbering doesn't matter), each row
    `same`, `changed` (with the changed facts) or `missing`, and the risk a
    change carries on the right-hand side."""
    return ApiResponse(data=await service.compare(body))
