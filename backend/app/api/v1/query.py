"""
Contract Q&A: hybrid RAG with verified citations (Phase 7).
Phase 8 routes complex questions through the LangGraph agent.

The handler stays thin: validation in schemas, logic in QueryService.
The permission dependency is declared first, so unauthorized requests are
rejected before a database session is opened or any model is called.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.dependencies import QueryRunnerDep, QueryServiceDep
from app.schemas.common import ApiResponse
from app.schemas.query import QueryRequest, QueryResponse

router = APIRouter(tags=["query"])


@router.post(
    "/query",
    summary="Ask a question over one or more contracts",
    response_model=ApiResponse[QueryResponse],
)
async def ask(
    _: QueryRunnerDep, body: QueryRequest, service: QueryServiceDep
) -> ApiResponse[QueryResponse]:
    """Answer from the organization's contracts, citing page, section and clause.

    `insufficient_evidence=true` means the contracts did not contain the
    answer; the response then says so instead of guessing.
    """
    return ApiResponse(data=await service.ask(body))
