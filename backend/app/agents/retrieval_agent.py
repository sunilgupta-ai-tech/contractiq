"""
Retrieval nodes: retrieve -> rerank -> validate -> (refine -> retrieve).

retrieve  one `search_contracts` tool call per query, through the tool
          registry (permission + tenant injection + budget). A query that
          was already searched is skipped — duplicate-action detection, so a
          refinement that repeats itself costs nothing.
rerank    each query's hits are reranked against *that* query, then merged
          round-robin, so every part of a multi-part question keeps its own
          best evidence instead of one part crowding out the others.
validate  decides what happens next (see `after_validate`):
            nothing found in scope   -> not_found  (retrying can't help)
            relevant evidence        -> answer
            weak evidence, retries   -> refine
            left and budget left
            weak, nothing left       -> answer     (the model may still say
                                                    INSUFFICIENT_EVIDENCE)
refine    asks the model for alternative wording of the weak queries (legal
          synonyms). No usable new query ends the retry loop immediately.

"Relevant" is judged cheaply: does any top chunk share content words with
the question (or carry a clause number the question names)? Dense search
always returns *something*; this catches the case where that something is
unrelated.
"""

from __future__ import annotations

import math
import time
from typing import Any

from app.agents.prompts import REFINE_PROMPT, clean_queries, parse_json_object
from app.agents.state import AgentState
from app.agents.supervisor import AgentDeps
from app.agents.tools.registry import ToolError
from app.core.logging import get_logger
from app.llm.base import ChatMessage, LLMError
from app.rag.pipelines.qa import Step
from app.rag.reranker import referenced_clauses
from app.rag.types import RetrievedChunk
from app.vectorstore.sparse import tokenize

logger = get_logger(__name__)

# Share of the question's content words that must appear in some top chunk.
MIN_TERM_OVERLAP = 0.2


async def retrieve(state: AgentState, deps: AgentDeps) -> dict[str, Any]:
    started = time.perf_counter()
    candidates = dict(state.get("candidates") or {})
    calls = state.get("tool_calls", 0)
    errors: list[str] = []
    searched = 0
    for query in state.get("queries") or []:
        if query in candidates:
            continue  # already searched: never repeat an identical tool call
        try:
            hits = await deps.tools.call(
                "search_contracts",
                tenant_id=state["tenant_id"],
                role=state["role"],
                calls_so_far=calls,
                arguments={
                    "question": query,
                    "document_ids": state.get("document_ids"),
                    "version_ids": state.get("version_ids"),
                    "limit": deps.settings.retrieval_candidates,
                },
            )
        except ToolError as exc:
            logger.warning("tool_refused", extra={"reason": str(exc)})
            errors.append(f"retrieve:{exc}")
            break
        calls += 1
        searched += 1
        candidates[query] = hits
    found = sum(len(candidates.get(q, [])) for q in state.get("queries") or [])
    return {
        "candidates": candidates,
        "tool_calls": calls,
        "errors": errors,
        "steps": [
            _step("retrieve", "Hybrid search", f"{searched} search(es), {found} hits", started)
        ],
    }


async def rerank(state: AgentState, deps: AgentDeps) -> dict[str, Any]:
    started = time.perf_counter()
    queries = state.get("queries") or []
    candidates = state.get("candidates") or {}
    top_n = deps.settings.rerank_top_n
    per_query = max(2, math.ceil(top_n / max(len(queries), 1)))
    ranked_lists = [
        await deps.reranker.rerank(query, list(candidates.get(query, [])), per_query)
        for query in queries
    ]
    merged: list[RetrievedChunk] = []
    seen: set[str] = set()
    for position in range(per_query):  # round-robin: best of each query first
        for ranked in ranked_lists:
            if position < len(ranked) and ranked[position].chunk_id not in seen:
                seen.add(ranked[position].chunk_id)
                merged.append(ranked[position])
    merged = merged[:top_n]
    return {
        "reranked": merged,
        "steps": [_step("rerank", "Rerank", f"top {len(merged)} ({deps.reranker.name})", started)],
    }


def evidence_is_relevant(texts: list[str], chunks: list[RetrievedChunk]) -> bool:
    """True if any chunk names a clause one of `texts` names, or shares at
    least MIN_TERM_OVERLAP of the content words of one of `texts`.

    `texts` is the question *and* every search query run for it, so evidence
    found through a refined wording ("termination" for "end the deal") is
    judged against that wording, not only against the user's words.
    """
    for text in texts:
        clauses = referenced_clauses(text)
        terms = set(tokenize(text))
        for chunk in chunks:
            if clauses & {chunk.clause, chunk.section, *chunk.clauses}:
                return True
            if terms:
                words = set(tokenize(" ".join(chunk.heading_path) + " " + chunk.text))
                if len(terms & words) / len(terms) >= MIN_TERM_OVERLAP:
                    return True
    return False


async def validate(state: AgentState, deps: AgentDeps) -> dict[str, Any]:
    started = time.perf_counter()
    top = state.get("reranked") or []
    texts = [state["standalone_question"], *(state.get("queries") or [])]
    ok = bool(top) and evidence_is_relevant(texts, top)
    detail = "no evidence in scope" if not top else ("relevant" if ok else "weak evidence")
    return {
        "evidence_ok": ok,
        "steps": [_step("validate", "Check evidence", detail, started)],
    }


def after_validate(state: AgentState, *, max_retries: int, max_tool_calls: int) -> str:
    """Conditional edge out of `validate` (see module docstring)."""
    if not state.get("reranked"):
        return "not_found"
    if state.get("evidence_ok"):
        return "answer"
    retries_left = state.get("retry_count", 0) < max_retries
    budget_left = state.get("tool_calls", 0) < max_tool_calls
    return "refine" if retries_left and budget_left else "answer"


async def refine(state: AgentState, deps: AgentDeps) -> dict[str, Any]:
    started = time.perf_counter()
    searched = set(state.get("candidates") or {})
    new_queries: list[str] = []
    errors: list[str] = []
    for query in (state.get("queries") or [])[:2]:
        try:
            result = await deps.llm.generate(
                [ChatMessage(role="user", content=REFINE_PROMPT.format(query=query))],
                temperature=0.2,  # a little variety: we want *different* wording
                max_tokens=200,
            )
            plan = parse_json_object(result.text)
            proposals = clean_queries(plan.get("queries") if plan else None, limit=2)
        except LLMError as exc:
            errors.append(f"refine:{type(exc).__name__}")
            proposals = []
        new_queries += [q for q in proposals if q not in searched and q not in new_queries]

    retry = state.get("retry_count", 0) + 1
    if not new_queries:
        # Nothing new to try: jump the retry counter to the limit so the
        # next validate goes straight to answering with what we have.
        return {
            "retry_count": deps.settings.agent_max_retries,
            "errors": errors,
            "steps": [_step("refine", "Refine search", "no new wording found", started, "retry")],
        }
    return {
        # New wording first (reranking merges round-robin in this order, so
        # its evidence leads); earlier queries are kept so their hits stay in
        # the pool — they are not searched again, and a weak retry can't
        # lose earlier evidence.
        "queries": [*new_queries, *(state.get("queries") or [])],
        "retry_count": retry,
        "errors": errors,
        "steps": [
            _step(
                "refine",
                "Refine search",
                f"retry {retry}: {len(new_queries)} new",
                started,
                "retry",
            )
        ],
    }


def _step(key: str, label: str, detail: str, started: float, status: str = "done") -> Step:
    return Step(key, label, detail, round((time.perf_counter() - started) * 1000, 1), status)
