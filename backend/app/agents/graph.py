"""
The LangGraph agent for contract questions.

    START
      └─ understand ──(route by intent; Phase 8: all -> qa)──┐
                                                             ▼
                 ┌──────────────────────────────────────► retrieve
                 │                                           ▼
                 │                                        rerank
                 │                                           ▼
               refine ◄── weak, retries left ───────── validate ── nothing in scope ─► not_found
                                                             │
                                                     relevant (or out of retries)
                                                             ▼
                                                  context ─► generate ─► cite ─► END

Guardrails (all enforced in code):
  * retries        AGENT_MAX_RETRIES refine rounds
  * tool budget    AGENT_MAX_TOOL_CALLS searches per question (tools/registry.py)
  * step limit     LangGraph recursion_limit, derived from the retry limit, so a
                   bug in an edge condition can never loop forever
  * time limit     AGENT_TIMEOUT_S for the whole run
  * tenant safety  tenant_id/role live in state, set by the API; tools get them
                   from the registry, never from model output
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph

from app.agents import answering, retrieval_agent, supervisor
from app.agents.errors import AgentTimeoutError
from app.agents.prompts import AGENT_PROMPT_VERSION
from app.agents.results import AgentAnswer
from app.agents.state import AgentState
from app.agents.supervisor import AgentDeps
from app.agents.tools.registry import Tool, ToolRegistry
from app.core.config import Settings
from app.core.logging import get_logger
from app.core.security import Permission, Role
from app.llm.base import LLMProvider
from app.rag.pipelines.qa import NOT_FOUND_MESSAGE
from app.rag.prompts.system import PROMPT_VERSION
from app.rag.reranker import Reranker
from app.rag.retriever import Retriever
from app.rag.types import RetrievedChunk

logger = get_logger(__name__)


def build_tools(retriever: Retriever, max_calls: int) -> ToolRegistry:
    """The agent's tools. Each takes `tenant_id` from the registry only."""

    async def search_contracts(
        *,
        tenant_id: str,
        question: str,
        document_ids: Sequence[str] | None,
        version_ids: Sequence[str] | None,
        limit: int,
    ) -> list[RetrievedChunk]:
        return await retriever.retrieve(
            question,
            tenant_id=tenant_id,
            document_ids=document_ids,
            version_ids=version_ids,
            limit=limit,
        )

    async def get_sections(*, tenant_id: str, parent_ids: Sequence[str]) -> dict[str, Any]:
        return await retriever.parents(tenant_id=tenant_id, parent_ids=parent_ids)

    return ToolRegistry(
        [
            Tool(
                "search_contracts",
                "Hybrid search over the organization's contract clauses.",
                Permission.QUERY_RUN,
                search_contracts,
            ),
            Tool(
                "get_sections",
                "Full section text for matched clauses (small-to-big context).",
                Permission.QUERY_RUN,
                get_sections,
            ),
        ],
        max_calls=max_calls,
    )


def build_graph(deps: AgentDeps) -> Any:
    """Wire the nodes and edges (see module docstring) and compile."""
    settings = deps.settings

    def bind(node: Any) -> Any:
        async def run(state: AgentState) -> dict[str, Any]:
            result: dict[str, Any] = await node(state, deps)
            return result

        return run

    graph = StateGraph(AgentState)
    graph.add_node("understand", bind(supervisor.understand))
    graph.add_node("retrieve", bind(retrieval_agent.retrieve))
    graph.add_node("rerank", bind(retrieval_agent.rerank))
    graph.add_node("validate", bind(retrieval_agent.validate))
    graph.add_node("refine", bind(retrieval_agent.refine))
    graph.add_node("context", bind(answering.context))
    graph.add_node("generate", bind(answering.generate))
    graph.add_node("cite", bind(answering.cite))
    graph.add_node("not_found", bind(answering.not_found))

    graph.add_edge(START, "understand")
    graph.add_conditional_edges("understand", supervisor.route, {"qa": "retrieve"})
    graph.add_edge("retrieve", "rerank")
    graph.add_edge("rerank", "validate")
    graph.add_conditional_edges(
        "validate",
        lambda state: retrieval_agent.after_validate(
            state,
            max_retries=settings.agent_max_retries,
            max_tool_calls=settings.agent_max_tool_calls,
        ),
        {"refine": "refine", "answer": "context", "not_found": "not_found"},
    )
    graph.add_edge("refine", "retrieve")
    graph.add_edge("context", "generate")
    graph.add_edge("generate", "cite")
    graph.add_edge("cite", END)
    graph.add_edge("not_found", END)
    return graph.compile()


def step_limit(max_retries: int) -> int:
    """Upper bound on node executions: understand + 4 nodes per search round
    (retrieve, rerank, validate, refine) + the 3 answering nodes, plus slack.
    Reaching it means an edge condition is wrong, never normal operation."""
    return 1 + 4 * (max_retries + 1) + 3 + 4


class AgentRunner:
    def __init__(
        self, retriever: Retriever, reranker: Reranker, llm: LLMProvider, settings: Settings
    ) -> None:
        self.settings = settings
        deps = AgentDeps(
            tools=build_tools(retriever, settings.agent_max_tool_calls),
            reranker=reranker,
            llm=llm,
            settings=settings,
        )
        self.llm = llm
        self.graph = build_graph(deps)

    async def answer(
        self,
        question: str,
        *,
        tenant_id: str,
        role: Role,
        document_ids: Sequence[str] | None = None,
        version_ids: Sequence[str] | None = None,
        history: list[tuple[str, str]] | None = None,
    ) -> AgentAnswer:
        initial: AgentState = {
            "question": question,
            "tenant_id": tenant_id,
            "role": role,
            "document_ids": list(document_ids) if document_ids else None,
            "version_ids": list(version_ids) if version_ids else None,
            "history": history or [],
            "retry_count": 0,
            "tool_calls": 0,
            "steps": [],
            "flags": [],
            "errors": [],
        }
        try:
            final: AgentState = await asyncio.wait_for(
                self.graph.ainvoke(
                    initial,
                    config={"recursion_limit": step_limit(self.settings.agent_max_retries)},
                ),
                timeout=self.settings.agent_timeout_s,
            )
        except TimeoutError as exc:
            raise AgentTimeoutError(f"agent exceeded {self.settings.agent_timeout_s}s") from exc
        except GraphRecursionError:
            logger.error("agent_step_limit_reached")
            return AgentAnswer(
                answer=NOT_FOUND_MESSAGE,
                citations=[],
                insufficient_evidence=True,
                cited_fraction=0.0,
                steps=[],
                model=None,
                prompt_version=PROMPT_VERSION,
                standalone_question=question,
            )
        if final.get("errors"):
            logger.warning("agent_errors", extra={"errors": final["errors"]})
        result = final.get("llm_result")
        return AgentAnswer(
            answer=final.get("answer", NOT_FOUND_MESSAGE),
            citations=final.get("citations", []),
            insufficient_evidence=final.get("insufficient_evidence", True),
            cited_fraction=final.get("cited_fraction", 0.0),
            steps=final.get("steps", []),
            model=result.model if result else None,
            prompt_version=f"{PROMPT_VERSION}+{AGENT_PROMPT_VERSION}",
            prompt_tokens=result.prompt_tokens if result else None,
            completion_tokens=result.completion_tokens if result else None,
            injection_flags=final.get("flags", []),
            intent=final.get("intent", "qa"),
            standalone_question=final.get("standalone_question", question),
            queries=final.get("queries", []),
            retries=final.get("retry_count", 0),
            tool_calls=final.get("tool_calls", 0),
        )
