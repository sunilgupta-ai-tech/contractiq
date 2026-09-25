"""Request/response schemas for contract Q&A (POST /query)."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from pydantic import BaseModel, Field, StringConstraints

Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=2000)]


class QueryRequest(BaseModel):
    question: Question
    # Restrict the search to these documents; empty = all of the tenant's documents.
    document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    # Search these specific versions instead of each document's latest one.
    version_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    # Continue an existing conversation (follow-up questions); omit to start one.
    conversation_id: uuid.UUID | None = None


class CitationOut(BaseModel):
    index: int = Field(description="The [n] marker used in `answer`.")
    chunk_id: str
    document_id: str
    document_title: str | None
    version_id: str
    version_label: str
    page: int
    page_end: int
    section: str | None
    section_title: str | None
    clause: str | None
    clause_title: str | None
    quote: str
    score: float
    regions: list[dict[str, Any]] = Field(
        default_factory=list, description="Page + bounding box of the cited text (highlighting)."
    )
    clauses: list[str] = Field(
        default_factory=list, description="Every clause number the cited text covers."
    )


class StepOut(BaseModel):
    key: str
    label: str
    detail: str
    duration_ms: float
    status: str


class UsageOut(BaseModel):
    prompt_tokens: int | None
    completion_tokens: int | None


class QueryResponse(BaseModel):
    id: uuid.UUID = Field(description="The assistant message id.")
    conversation_id: uuid.UUID
    question: str
    answer: str
    citations: list[CitationOut]
    insufficient_evidence: bool = Field(
        description="True when the contracts did not contain the answer."
    )
    cited_fraction: float = Field(
        description="Share of answer sentences carrying a valid citation (0-1)."
    )
    steps: list[StepOut]
    model: str | None
    prompt_version: str
    latency_ms: int
    usage: UsageOut
