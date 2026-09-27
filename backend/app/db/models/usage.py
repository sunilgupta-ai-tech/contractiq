"""
AI usage per organization per month (Phase 22).

Durable counters in PostgreSQL (not Redis): they feed plan limits and are
the basis for billing, so they must survive a cache restart. One row per
organization and calendar month (UTC), updated with an atomic upsert.
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.base import TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class UsageCounter(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "usage_counters"
    __table_args__ = (UniqueConstraint("organization_id", "period"),)

    period: Mapped[str] = mapped_column(String(7), nullable=False)  # "2026-09"
    queries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    embedding_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    model_calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
