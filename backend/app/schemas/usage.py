"""Usage and plan limits of an organization (Phase 22)."""

from __future__ import annotations

from pydantic import BaseModel

from app.db.models import Plan


class UsagePeriodOut(BaseModel):
    model_config = {"from_attributes": True}

    period: str  # "2026-09"
    queries: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    embedding_tokens: int = 0
    model_calls: int = 0


class OrgLimitsOut(BaseModel):
    max_users: int | None
    max_documents: int | None
    max_storage_mb: int | None
    max_ai_queries_month: int | None
    max_ai_tokens_month: int | None


class OrgCurrentOut(BaseModel):
    active_users: int
    documents: int
    storage_bytes: int


class OrgUsageOut(BaseModel):
    """What the organization uses against its plan: now, and month by month."""

    plan: Plan
    limits: OrgLimitsOut
    current: OrgCurrentOut
    months: list[UsagePeriodOut]
