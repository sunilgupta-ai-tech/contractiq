"""
Answer cache (Phase 21): the same question over the same documents is not
paid for twice.

A cached answer is only ever served when everything that shaped it is the
same. The key is built from:

* the organization (tenant-prefixed key: never shared across tenants);
* the normalized question, the answer mode, and the documents/versions it
  was scoped to;
* the documents this user may NOT see (Phase 20) — users with different
  access never share an answer;
* the organization's corpus version (document count and last change), so
  any upload, re-processing, deletion or access change invalidates it;
* the prompt version and model, so a new prompt or model starts fresh.

Only first questions are cached (follow-ups depend on the conversation),
and only answers that found evidence. The cached copy costs no tokens: its
token counts are reported as zero.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.agents.results import AgentAnswer
from app.cache.redis import tenant_cache_key
from app.core.logging import get_logger
from app.guardrails.evidence_validator import ClaimCheck, GroundingReport
from app.rag.pipelines.qa import RagAnswer, Step
from app.rag.types import Citation

logger = get_logger(__name__)


def cache_key(
    tenant_id: str,
    *,
    question: str,
    mode: str,
    document_ids: list[str],
    version_ids: list[str],
    hidden_document_ids: list[str],
    corpus_version: str,
    prompt_version: str,
    model: str,
) -> str:
    parts = {
        "q": " ".join(question.lower().split()),
        "mode": mode,
        "docs": sorted(document_ids),
        "versions": sorted(version_ids),
        "hidden": sorted(hidden_document_ids),
        "corpus": corpus_version,
        "prompt": prompt_version,
        "model": model,
    }
    digest = hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()
    return tenant_cache_key(tenant_id, "answer", digest)


def to_json(answer: RagAnswer) -> str:
    return json.dumps(asdict(answer), ensure_ascii=False)


def from_json(raw: str) -> RagAnswer:
    data: dict[str, Any] = json.loads(raw)
    grounding = data.get("grounding")
    common: dict[str, Any] = dict(
        answer=data["answer"],
        citations=[Citation(**c) for c in data["citations"]],
        insufficient_evidence=data["insufficient_evidence"],
        cited_fraction=data["cited_fraction"],
        steps=[Step(**s) for s in data["steps"]],
        model=data["model"],
        prompt_version=data["prompt_version"],
        prompt_tokens=0,  # served from cache: no model call
        completion_tokens=0,
        injection_flags=list(data.get("injection_flags") or []),
        grounding=(
            GroundingReport(
                score=grounding["score"],
                claims=[ClaimCheck(**c) for c in grounding["claims"]],
            )
            if grounding
            else None
        ),
    )
    if "intent" in data:  # an agent answer keeps what the agent did
        return AgentAnswer(
            **common,
            intent=data["intent"],
            standalone_question=data.get("standalone_question", ""),
            queries=list(data.get("queries") or []),
            retries=int(data.get("retries") or 0),
            tool_calls=int(data.get("tool_calls") or 0),
        )
    return RagAnswer(**common)


async def get(redis: Redis | None, key: str) -> RagAnswer | None:
    if redis is None:
        return None
    try:
        raw = await redis.get(key)
    except RedisError as exc:
        logger.warning("answer_cache_unavailable", extra={"error": repr(exc)})
        return None
    if raw is None:
        return None
    try:
        answer = from_json(raw)
    except (ValueError, KeyError, TypeError):
        return None  # written by an older version: ignore
    answer.steps.insert(
        0,
        Step(
            key="cache",
            label="Answer cache",
            detail="Same question, same documents",
            duration_ms=0.0,
        ),
    )
    return answer


async def put(redis: Redis | None, key: str, answer: RagAnswer, ttl_s: int) -> None:
    if redis is None or ttl_s <= 0:
        return
    try:
        await redis.set(key, to_json(answer), ex=ttl_s)
    except RedisError as exc:
        logger.warning("answer_cache_unavailable", extra={"error": repr(exc)})
