"""Request/response models for contract analysis (Phase 10): clause
extraction, summaries, risk analysis, comparison and portfolio summaries."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.query import CitationOut

DISCLAIMER = (
    "AI-assisted analysis, not legal advice. Review flagged clauses with a qualified "
    "professional before relying on them."
)

MAX_DOCUMENTS = 50


# --- Shared ------------------------------------------------------------------------------


class VersionOut(BaseModel):
    document_id: uuid.UUID
    document_title: str
    contract_type: str
    version_id: uuid.UUID
    version_label: str


class EvidenceOut(BaseModel):
    """Where an extracted clause was found — enough to open and highlight it."""

    chunk_id: str
    page: int
    page_end: int
    section: str | None
    section_title: str | None
    clause: str | None
    clause_title: str | None
    heading_path: list[str]
    regions: list[dict[str, Any]]


class ExtractedClauseOut(BaseModel):
    topic: str = Field(description="Stable topic key, e.g. 'liability_cap'.")
    label: str
    found: bool
    error: bool = Field(description="Extraction failed for this topic; `found` is unknown.")
    verified: bool = Field(description="`quote` appears word for word in the contract.")
    quote: str | None
    summary: str | None
    attributes: dict[str, Any] = Field(
        description="Typed facts, e.g. {'notice_days': 60}. null = not stated."
    )
    clause: str | None
    page: int | None
    evidence: EvidenceOut | None


class KeyTermOut(BaseModel):
    label: str
    value: str
    topic: str
    clause: str | None
    page: int | None


class KeyDateOut(BaseModel):
    date: dt.date
    label: str
    kind: Literal["start", "expiry", "renewal", "notice"]
    document_id: uuid.UUID
    document_title: str
    clause: str | None
    page: int | None


class RiskCounts(BaseModel):
    high: int = 0
    medium: int = 0
    low: int = 0


# --- Clause extraction ----------------------------------------------------------------------


class DocumentAnalysisRequest(BaseModel):
    document_id: uuid.UUID
    version_id: uuid.UUID | None = Field(
        default=None, description="A specific version; default: the current version."
    )
    refresh: bool = Field(default=False, description="Ignore the cached analysis.")


class ExtractClausesResponse(BaseModel):
    version: VersionOut
    clauses: list[ExtractedClauseOut]
    model: str
    generated_at: dt.datetime
    cached: bool


# --- Summary -------------------------------------------------------------------------------


class ObligationOut(BaseModel):
    party: str
    obligation: str
    clause: str | None
    page: int | None
    chunk_id: str


class SummaryResponse(BaseModel):
    version: VersionOut
    overview: str = Field(description="Executive summary with [n] markers into `citations`.")
    citations: list[CitationOut]
    obligations: list[ObligationOut]
    key_terms: list[KeyTermOut]
    key_dates: list[KeyDateOut]
    risk_counts: RiskCounts
    model: str
    generated_at: dt.datetime
    disclaimer: str = DISCLAIMER


# --- Risk ----------------------------------------------------------------------------------


class RiskAnalysisRequest(BaseModel):
    document_ids: list[uuid.UUID] = Field(
        default_factory=list,
        max_length=MAX_DOCUMENTS,
        description="Documents to analyse (current versions); empty = the organisation's "
        "most recently updated processed documents.",
    )
    version_id: uuid.UUID | None = Field(
        default=None, description="Analyse exactly this version instead."
    )


class RiskFindingOut(BaseModel):
    id: str
    rule: str
    title: str
    severity: Literal["high", "medium", "low"]
    topic: str
    rationale: str
    missing: bool = Field(description="A protective clause was not found (no excerpt).")
    document_id: uuid.UUID
    document_title: str | None
    version_id: uuid.UUID
    version_label: str
    clause: str | None
    page: int | None
    excerpt: str | None
    regions: list[dict[str, Any]] | None
    status: Literal["open"] = "open"


class RiskAnalysisResponse(BaseModel):
    findings: list[RiskFindingOut]
    counts: RiskCounts
    documents_analyzed: int
    pending_document_ids: list[uuid.UUID] = Field(
        description="Not analysed yet: queued in the background; ask again shortly."
    )
    disclaimer: str = DISCLAIMER


# --- Comparison ----------------------------------------------------------------------------


class CompareRequest(BaseModel):
    left_version_id: uuid.UUID
    right_version_id: uuid.UUID


class SideOut(BaseModel):
    clause: str | None
    page: int | None
    text: str
    summary: str | None
    attributes: dict[str, Any]
    regions: list[dict[str, Any]]


class ComparisonRowOut(BaseModel):
    topic: str
    label: str
    diff: Literal["same", "changed", "missing"]
    note: str
    left: SideOut | None
    right: SideOut | None
    similarity: float | None
    risk: Literal["high", "medium", "low"] | None


class DiffCounts(BaseModel):
    same: int = 0
    changed: int = 0
    missing: int = 0


class CompareResponse(BaseModel):
    left: VersionOut
    right: VersionOut
    rows: list[ComparisonRowOut]
    counts: DiffCounts
    disclaimer: str = DISCLAIMER


# --- Portfolio -----------------------------------------------------------------------------


class PortfolioRequest(BaseModel):
    document_ids: list[uuid.UUID] = Field(
        default_factory=list,
        max_length=MAX_DOCUMENTS,
        description="Empty = the organisation's most recently updated processed documents.",
    )


class PortfolioDocumentOut(BaseModel):
    version: VersionOut
    key_terms: list[KeyTermOut]
    risk_counts: RiskCounts
    highest_risk: Literal["high", "medium", "low"] | None
    next_date: KeyDateOut | None


class PortfolioResponse(BaseModel):
    documents: list[PortfolioDocumentOut]
    upcoming_dates: list[KeyDateOut] = Field(description="Dates from today on, soonest first.")
    risk_totals: RiskCounts
    pending_document_ids: list[uuid.UUID]
    generated_at: dt.datetime
    disclaimer: str = DISCLAIMER
