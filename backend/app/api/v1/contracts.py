"""
Contract intelligence: summaries and clause extraction (Phase 10).

Handlers stay thin: validation in schemas, logic in ContractService. The
permission dependency is declared first, so unauthorized requests are
rejected before a database session is opened or any model is called.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.dependencies import AnalystDep, ContractServiceDep
from app.schemas.analysis import DocumentAnalysisRequest, ExtractClausesResponse, SummaryResponse
from app.schemas.common import ApiResponse

router = APIRouter(tags=["contracts"])


@router.post(
    "/contracts/summarize",
    summary="Executive summary with cited obligations and key dates",
    response_model=ApiResponse[SummaryResponse],
)
async def post_contracts_summarize(
    _: AnalystDep, body: DocumentAnalysisRequest, service: ContractServiceDep
) -> ApiResponse[SummaryResponse]:
    """Overview with [n] citations, obligations, key terms and dates (including
    the computed non-renewal notice deadline) and risk counts. Cached per
    version; `refresh=true` recomputes."""
    return ApiResponse(data=await service.summarize(body))


@router.post(
    "/contracts/extract-clauses",
    summary="Extract standard clauses (termination, liability, ...)",
    response_model=ApiResponse[ExtractClausesResponse],
)
async def post_contracts_extract_clauses(
    _: AnalystDep, body: DocumentAnalysisRequest, service: ContractServiceDep
) -> ApiResponse[ExtractClausesResponse]:
    """One entry per standard topic: found or not, a verified quote, typed
    facts (e.g. notice days) and where it is. Cached per version."""
    return ApiResponse(data=await service.extract_clauses(body))
