"""Agent exceptions, kept free of LangGraph imports so the API can handle
them without loading the agent (see services/query_service._agent_runner)."""


class AgentTimeoutError(Exception):
    """The agent run exceeded AGENT_TIMEOUT_S."""
