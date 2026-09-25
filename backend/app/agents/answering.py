"""
Answering nodes: context -> generate -> cite, plus not_found.

These reuse the Phase 7 building blocks (small-to-big context, the
versioned prompt, citation verification) so the agent and the fast path
answer and cite in exactly the same way. The differences are upstream: the
agent searches with a rewritten / decomposed / refined question.

Parent sections are fetched through the tool registry (`get_sections`), like
searches, so every data access by the agent passes the same permission,
tenant and budget checks.
"""

from __future__ import annotations

import time
from typing import Any

from app.agents.state import AgentState
from app.agents.supervisor import AgentDeps
from app.agents.tools.registry import ToolError
from app.core.logging import get_logger
from app.guardrails.prompt_injection import scan_for_injection
from app.llm.base import LLMBlockedError
from app.rag.context import build_evidence
from app.rag.pipelines.qa import BLOCKED_MESSAGE, NOT_FOUND_MESSAGE, Step, generate_answer
from app.rag.prompts.system import INSUFFICIENT_EVIDENCE, build_messages
from app.services.citation_service import resolve_citations

logger = get_logger(__name__)


async def context(state: AgentState, deps: AgentDeps) -> dict[str, Any]:
    started = time.perf_counter()
    top = state.get("reranked") or []
    parent_ids = [c.parent_id for c in top if c.parent_id]
    errors: list[str] = []
    try:
        parents = await deps.tools.call(
            "get_sections",
            tenant_id=state["tenant_id"],
            role=state["role"],
            calls_so_far=0,  # section lookups don't count against the search budget
            arguments={"parent_ids": parent_ids},
        )
    except ToolError as exc:
        errors.append(f"context:{exc}")
        parents = {}  # fall back to the matched clauses themselves
    blocks = build_evidence(top, parents, max_tokens=deps.settings.context_max_tokens)
    flags = [
        f"evidence[{b.number}]:{rule}"
        for b in blocks
        for rule in scan_for_injection(b.text).matched_rules
    ]
    if flags:
        logger.warning("prompt_injection_suspected", extra={"rules": flags})
    return {
        "evidence": blocks,
        "flags": flags,
        "errors": errors,
        "steps": [_step("context", "Build context", f"{len(blocks)} evidence blocks", started)],
    }


async def generate(state: AgentState, deps: AgentDeps) -> dict[str, Any]:
    started = time.perf_counter()
    messages = build_messages(
        state["standalone_question"], state.get("evidence") or [], state.get("history")
    )
    try:
        result = await generate_answer(
            deps.llm, messages, max_tokens=deps.settings.llm_max_output_tokens
        )
    except LLMBlockedError:
        logger.warning("llm_blocked")
        return {
            "llm_result": None,
            "answer": BLOCKED_MESSAGE,
            "insufficient_evidence": True,
            "steps": [_step("generate", "Generate answer", "blocked", started, "retry")],
        }
    return {
        "llm_result": result,
        "steps": [_step("generate", "Generate answer", result.model, started)],
    }


async def cite(state: AgentState, deps: AgentDeps) -> dict[str, Any]:
    started = time.perf_counter()
    result = state.get("llm_result")
    if result is None:  # blocked: `generate` already set the answer
        return {"citations": [], "cited_fraction": 0.0}
    if result.text.strip().strip(".").upper() == INSUFFICIENT_EVIDENCE:
        return {
            "answer": NOT_FOUND_MESSAGE,
            "citations": [],
            "cited_fraction": 0.0,
            "insufficient_evidence": True,
            "steps": [_step("cite", "Verify citations", "model found no answer", started)],
        }
    cited = resolve_citations(result.text, state.get("evidence") or [])
    return {
        "answer": cited.text,
        "citations": cited.citations,
        "cited_fraction": cited.cited_fraction,
        "insufficient_evidence": False,
        "steps": [_step("cite", "Verify citations", f"{len(cited.citations)} citations", started)],
    }


async def not_found(state: AgentState, deps: AgentDeps) -> dict[str, Any]:
    """Nothing in scope matched: answer honestly without calling the model."""
    return {
        "answer": NOT_FOUND_MESSAGE,
        "citations": [],
        "cited_fraction": 0.0,
        "insufficient_evidence": True,
        "llm_result": None,
    }


def _step(key: str, label: str, detail: str, started: float, status: str = "done") -> Step:
    return Step(key, label, detail, round((time.perf_counter() - started) * 1000, 1), status)
