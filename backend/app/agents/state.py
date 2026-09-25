"""
LangGraph agent state.

The state is a TypedDict that every node reads and partially updates. Two
fields accumulate across nodes (their Annotated reducer is `operator.add`):
`steps` (the timing trail shown in the UI) and `flags` (injection warnings).
Every other field is simply overwritten by the node that returns it.

Security: `tenant_id` and `role` are set once by the API layer from the
signed token and are never written by any node. Tools read them from state
(see tools/registry.py); a model's output can never change them, so the
model cannot redirect a search to another tenant's data.
"""

from __future__ import annotations

import operator
from typing import Annotated, Literal, TypedDict

from app.core.security import Role
from app.llm.base import LLMResult
from app.rag.pipelines.qa import Step
from app.rag.types import Citation, EvidenceBlock, RetrievedChunk

Intent = Literal["qa", "compare", "risk", "summarize", "extract", "multi_document"]
INTENTS: frozenset[str] = frozenset(
    {"qa", "compare", "risk", "summarize", "extract", "multi_document"}
)


class AgentState(TypedDict, total=False):
    # --- set by the API layer; read-only for every node ---
    question: str
    tenant_id: str
    role: Role
    document_ids: list[str] | None
    version_ids: list[str] | None
    history: list[tuple[str, str]]

    # --- understand ---
    intent: Intent
    standalone_question: str  # follow-up rewritten to stand on its own
    queries: list[str]  # what to search for (sub-questions, later refinements)

    # --- retrieve / rerank / validate ---
    candidates: dict[str, list[RetrievedChunk]]  # query -> hits
    reranked: list[RetrievedChunk]
    evidence_ok: bool
    retry_count: int
    tool_calls: int

    # --- answer ---
    evidence: list[EvidenceBlock]
    llm_result: LLMResult | None
    answer: str
    citations: list[Citation]
    cited_fraction: float
    insufficient_evidence: bool

    # --- accumulated across nodes ---
    steps: Annotated[list[Step], operator.add]
    flags: Annotated[list[str], operator.add]
    errors: Annotated[list[str], operator.add]


MAX_RETRIES = 2
MAX_ITERATIONS = 8
