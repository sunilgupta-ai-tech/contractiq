"""
AI-assisted risk analysis (Phase 10). Output is advisory and must be
reviewed by a qualified professional.

Handlers stay thin: validation in schemas, logic in RiskService.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.dependencies import AnalystDep, RiskServiceDep
from app.schemas.analysis import RiskAnalysisRequest, RiskAnalysisResponse
from app.schemas.common import ApiResponse

router = APIRouter(tags=["contracts"])


@router.post(
    "/contracts/risk-analysis",
    summary="Flag potentially high-risk clauses with evidence",
    response_model=ApiResponse[RiskAnalysisResponse],
)
async def post_contracts_risk_analysis(
    _: AnalystDep, body: RiskAnalysisRequest, service: RiskServiceDep
) -> ApiResponse[RiskAnalysisResponse]:
    """Rule-based findings over extracted clauses, most severe first. Documents
    not analysed yet are queued and listed in `pending_document_ids`."""
    return ApiResponse(data=await service.analyze(body))
