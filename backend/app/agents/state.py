"""
LangGraph agent state (Phase 8).

The state is a plain TypedDict so it serialises cleanly for checkpointing
and tracing. `tenant_id` is set by the API from the authenticated token and
is read-only for every node — tools receive it from state, never from LLM
output, so the model cannot redirect a tool to another tenant's data.
"""

from __future__ import annotations

from typing import Literal, TypedDict


class Citation(TypedDict):
    document_id: str
    version_id: str
    page: int
    section: str | None
    clause: str | None
    chunk_id: str
    quote: str


class RetrievedChunk(TypedDict):
    chunk_id: str
    document_id: str
    version_id: str
    text: str
    page: int
    section: str | None
    clause: str | None
    score: float


Intent = Literal["qa", "compare", "risk", "summarize", "extract", "multi_document"]


class AgentState(TypedDict, total=False):
    question: str
    tenant_id: str  # immutable — set by the API layer
    intent: Intent
    documents: list[str]
    retrieved_chunks: list[RetrievedChunk]
    reranked_chunks: list[RetrievedChunk]
    clauses: list[dict[str, object]]
    tool_results: list[dict[str, object]]
    answer: str
    citations: list[Citation]
    retry_count: int
    errors: list[str]


MAX_RETRIES = 2
MAX_ITERATIONS = 8
