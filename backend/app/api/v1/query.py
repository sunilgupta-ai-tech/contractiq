"""
Contract Q&A. Phase 7: hybrid RAG with citations; Phase 8: routed through the LangGraph agent.

Implementation lands in Phase 7. The routes are registered now so the
API contract is visible in OpenAPI and the frontend can integrate against it.
Route handlers stay thin: validation in schemas, logic in services.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.exceptions import NotImplementedYetError

router = APIRouter(tags=["query"])
PHASE = 7


@router.post("/query", summary="Ask a question over one or more contracts", status_code=501)
async def post_query() -> None:
    raise NotImplementedYetError("Ask a question over one or more contracts", PHASE)
