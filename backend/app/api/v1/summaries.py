"""
Portfolio-level summaries across many contracts (Phase 10).

Handlers stay thin: validation in schemas, logic in ContractService.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.dependencies import AnalysisRateLimitDep, AnalystDep, ContractServiceDep
from app.schemas.analysis import PortfolioRequest, PortfolioResponse
from app.schemas.common import ApiResponse

router = APIRouter(tags=["contracts"])


@router.post(
    "/contracts/portfolio-summary",
    summary="Summarize obligations across a set of contracts",
    response_model=ApiResponse[PortfolioResponse],
)
async def post_contracts_portfolio_summary(
    _: AnalystDep, _limit: AnalysisRateLimitDep, body: PortfolioRequest, service: ContractServiceDep
) -> ApiResponse[PortfolioResponse]:
    """Key terms, risk counts and upcoming dates (renewals, expiries, notice
    deadlines) per contract and across the portfolio. Documents not analysed
    yet are queued and listed in `pending_document_ids`."""
    return ApiResponse(data=await service.portfolio(body))
