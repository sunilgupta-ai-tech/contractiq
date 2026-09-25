"""
Supervisor: understand the question, then route it.

understand (graph node)
-----------------------
Turns the user's question into what to search for:
  * a follow-up ("and for the Customer?") is rewritten into a standalone
    question using the conversation history;
  * a multi-part question ("compare the notice periods in the MSA and the
    SOW") is split into up to AGENT_MAX_SUB_QUESTIONS focused searches.

This needs one LLM call, so it only happens when it can help: when there
is conversation history, or the question looks multi-part (comparison
words, several clause numbers, several question marks). A simple,
standalone question skips it — no extra latency or cost.

If the planning reply is unusable (not JSON, empty, unknown intent) or the
call fails, the original question is used as-is. Planning is an
optimisation; it must never be the reason a question fails.

route
-----
Maps the intent to a specialist. In Phase 8 every intent uses the
retrieval-QA path; compare / risk / summarize / extract get dedicated
specialists in Phase 10 (see comparison_agent.py, risk_agent.py).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, cast

from app.agents.prompts import UNDERSTAND_PROMPT, clean_queries, parse_json_object
from app.agents.state import INTENTS, AgentState, Intent
from app.agents.tools.registry import ToolRegistry
from app.core.config import Settings
from app.core.logging import get_logger
from app.llm.base import ChatMessage, LLMError, LLMProvider
from app.rag.pipelines.qa import Step
from app.rag.reranker import Reranker, referenced_clauses

logger = get_logger(__name__)

_MULTI_PART = re.compile(
    r"\b(compare|comparison|differ(?:ence|ent|s)?|versus|vs\.?|across|between|each|both|"
    r"all (?:the |our )?(?:contracts|agreements|documents|vendors))\b",
    re.IGNORECASE,
)
HISTORY_ANSWER_CHARS = 600  # enough to resolve references, bounded prompt size


@dataclass
class AgentDeps:
    """Everything the nodes need, injected once when the graph is built."""

    tools: ToolRegistry
    reranker: Reranker
    llm: LLMProvider
    settings: Settings


def needs_planning(question: str, history: list[tuple[str, str]]) -> bool:
    return bool(
        history
        or _MULTI_PART.search(question)
        or question.count("?") > 1
        or len(referenced_clauses(question)) > 1
    )


async def understand(state: AgentState, deps: AgentDeps) -> dict[str, Any]:
    started = time.perf_counter()
    question = state["question"]
    history = state.get("history") or []
    if not needs_planning(question, history):
        return {
            "intent": "qa",
            "standalone_question": question,
            "queries": [question],
            "steps": [_step(started, "simple question, no planning call")],
        }

    plan: dict[str, Any] | None = None
    errors: list[str] = []
    try:
        result = await deps.llm.generate(
            [
                ChatMessage(role="system", content=UNDERSTAND_PROMPT),
                ChatMessage(role="user", content=_planning_input(question, history)),
            ],
            temperature=0.0,
            max_tokens=400,
        )
        plan = parse_json_object(result.text)
    except LLMError as exc:
        logger.warning("planning_failed", extra={"error": type(exc).__name__})
        errors.append(f"understand:{type(exc).__name__}")

    intent = plan.get("intent") if plan else None
    if intent not in INTENTS:
        intent = "qa"
    standalone = plan.get("standalone_question") if plan else None
    if not isinstance(standalone, str) or not standalone.strip():
        standalone = question
    limit = deps.settings.agent_max_sub_questions
    queries = clean_queries(plan.get("sub_questions") if plan else None, limit=limit)
    queries = queries or [standalone]
    detail = f"intent={intent}, {len(queries)} search(es)" + ("" if plan else ", fallback")
    return {
        "intent": cast(Intent, intent),
        "standalone_question": standalone.strip(),
        "queries": queries,
        "steps": [_step(started, detail)],
        "errors": errors,
    }


def route(state: AgentState) -> str:
    """Intent -> specialist. Phase 8: everything goes to retrieval QA."""
    return "qa"


def _planning_input(question: str, history: list[tuple[str, str]]) -> str:
    lines = ["Conversation so far:"] if history else []
    for previous_question, previous_answer in history:
        lines.append(f"User: {previous_question}")
        lines.append(f"Assistant: {previous_answer[:HISTORY_ANSWER_CHARS]}")
    lines.append(f"\nNew question: {question}")
    return "\n".join(lines)


def _step(started: float, detail: str) -> Step:
    return Step(
        "understand",
        "Understand question",
        detail,
        round((time.perf_counter() - started) * 1000, 1),
    )
