"""
AI usage accounting and limits (Phase 22).

How usage is counted
--------------------
Work that spends model tokens for an organization opens a *tally*
(`start_tally`): a question, a contract analysis request, a document being
processed. Every model and embedding call made while it is open — however
deep in the pipeline, including concurrent calls — adds to it (the
monitoring wrappers call `add_llm` / `add_embedding`). When the work ends,
`record` adds the tally to the organization's row for the month in
PostgreSQL with one atomic upsert.

Counters live in PostgreSQL, not Redis: they drive plan limits and are the
basis for billing, so they must survive a cache restart. Embedding tokens
are estimated from text length (providers do not report them).

Limits
------
`ensure_ai_allowance` refuses new questions and analyses once the month's
query or token allowance is used up (403 PLAN_LIMIT_REACHED). Document
processing that is already queued still completes.
"""

from __future__ import annotations

import contextvars
import uuid
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import PlanLimitError
from app.db.models import Organization, UsageCounter
from app.schemas.usage import OrgCurrentOut, OrgLimitsOut, OrgUsageOut, UsagePeriodOut
from app.services.plans import usage_of

T = TypeVar("T")


@dataclass
class UsageTally:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    embedding_tokens: int = 0
    model_calls: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens + self.embedding_tokens


_current: contextvars.ContextVar[UsageTally | None] = contextvars.ContextVar(
    "usage_tally", default=None
)


@contextmanager
def start_tally() -> Iterator[UsageTally]:
    """Count the model usage of the work done inside the block."""
    tally = UsageTally()
    token = _current.set(tally)
    try:
        yield tally
    finally:
        _current.reset(token)


def begin_tally() -> tuple[UsageTally, contextvars.Token[UsageTally | None]]:
    """Like `start_tally` for code that cannot wrap its work in a block
    (the worker task); pair with `end_tally`."""
    tally = UsageTally()
    return tally, _current.set(tally)


def end_tally(token: contextvars.Token[UsageTally | None]) -> None:
    _current.reset(token)


def add_llm(prompt_tokens: int | None, completion_tokens: int | None) -> None:
    tally = _current.get()
    if tally is not None:
        tally.prompt_tokens += prompt_tokens or 0
        tally.completion_tokens += completion_tokens or 0
        tally.model_calls += 1


def add_embedding(tokens: int) -> None:
    tally = _current.get()
    if tally is not None:
        tally.embedding_tokens += tokens


def current_period(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).strftime("%Y-%m")


async def record(
    session: AsyncSession, tenant_id: uuid.UUID, tally: UsageTally, *, queries: int = 0
) -> None:
    """Add to this month's counters (atomic upsert; the caller commits)."""
    if not (queries or tally.model_calls or tally.embedding_tokens):
        return
    values = {
        "queries": queries,
        "prompt_tokens": tally.prompt_tokens,
        "completion_tokens": tally.completion_tokens,
        "embedding_tokens": tally.embedding_tokens,
        "model_calls": tally.model_calls,
    }
    stmt = insert(UsageCounter).values(
        id=uuid.uuid4(), organization_id=tenant_id, period=current_period(), **values
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_usage_counters_organization_id",
        set_={k: getattr(UsageCounter, k) + stmt.excluded[k] for k in values}
        | {"updated_at": datetime.now(UTC)},
    )
    await session.execute(stmt)


async def month_usage(
    session: AsyncSession, tenant_id: uuid.UUID, period: str | None = None
) -> UsageCounter | None:
    return (
        await session.execute(
            select(UsageCounter).where(
                UsageCounter.organization_id == tenant_id,
                UsageCounter.period == (period or current_period()),
            )
        )
    ).scalar_one_or_none()


async def ensure_ai_allowance(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    org = await session.get(Organization, tenant_id)
    if org is None or (org.max_ai_queries_month is None and org.max_ai_tokens_month is None):
        return
    used = await month_usage(session, tenant_id)
    queries = used.queries if used else 0
    tokens = (used.prompt_tokens + used.completion_tokens + used.embedding_tokens) if used else 0
    if org.max_ai_queries_month is not None and queries >= org.max_ai_queries_month:
        raise PlanLimitError(
            f"Your plan's {org.max_ai_queries_month:,} AI questions for this month are used up.",
            details={"limit": "ai_queries", "max": org.max_ai_queries_month},
        )
    if org.max_ai_tokens_month is not None and tokens >= org.max_ai_tokens_month:
        raise PlanLimitError(
            "Your plan's AI usage for this month is used up.",
            details={"limit": "ai_tokens", "max": org.max_ai_tokens_month},
        )


class AIMeter:
    """Runs one piece of AI work for an organization (Phase 22): checks the
    month's allowance first, counts every model call it makes, and records
    the usage afterwards."""

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id

    async def run(self, work: Callable[[], Awaitable[T]], *, queries: int = 0) -> T:
        await ensure_ai_allowance(self.session, self.tenant_id)
        with start_tally() as tally:
            result = await work()
        await record(self.session, self.tenant_id, tally, queries=queries)
        await self.session.commit()
        return result


async def organization_usage(
    session: AsyncSession, tenant_id: uuid.UUID, *, months: int = 6
) -> OrgUsageOut:
    """Plan, limits, current storage/users/documents and the last months of AI usage."""
    org = await session.get(Organization, tenant_id)
    assert org is not None
    now = await usage_of(session, tenant_id)
    rows = (
        (
            await session.execute(
                select(UsageCounter)
                .where(UsageCounter.organization_id == tenant_id)
                .order_by(UsageCounter.period.desc())
                .limit(months)
            )
        )
        .scalars()
        .all()
    )
    periods = [UsagePeriodOut.model_validate(r) for r in rows]
    if not periods or periods[0].period != current_period():
        periods.insert(0, UsagePeriodOut(period=current_period()))
    return OrgUsageOut(
        plan=org.plan,
        limits=OrgLimitsOut(
            max_users=org.max_users,
            max_documents=org.max_documents,
            max_storage_mb=org.max_storage_mb,
            max_ai_queries_month=org.max_ai_queries_month,
            max_ai_tokens_month=org.max_ai_tokens_month,
        ),
        current=OrgCurrentOut(
            active_users=now.active_users, documents=now.documents, storage_bytes=now.storage_bytes
        ),
        months=periods[:months],
    )
