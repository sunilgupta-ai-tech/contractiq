"""The agent's result type, kept free of LangGraph imports so the API can
use it without loading the agent (see services/query_service._agent_runner)."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.rag.pipelines.qa import RagAnswer


@dataclass
class AgentAnswer(RagAnswer):
    """A RagAnswer plus what the agent did to get there."""

    intent: str = "qa"
    standalone_question: str = ""
    queries: list[str] = field(default_factory=list)
    retries: int = 0
    tool_calls: int = 0
