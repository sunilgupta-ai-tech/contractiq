from __future__ import annotations

from sqlalchemy import Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.base import TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class EvaluationRun(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """One run of the golden dataset against a pipeline configuration.

    `config` snapshots chunker/embedding/retriever/reranker/prompt/LLM
    versions so metric changes can be attributed to a specific change.
    """

    __tablename__ = "evaluation_runs"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    dataset_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="PENDING", nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    config: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict, nullable=False)
    # {"recall@5": 0.91, "mrr": 0.78, "groundedness": 0.94, ...}
    metrics: Mapped[dict[str, float]] = mapped_column(JSONB, default=dict, nullable=False)
