"""
Tool guardrails: limits on what an agent run may do.

Per-run limits (Phase 8, enforced in code, not by prompting):

    max iterations       AGENT_MAX_RETRIES refine rounds; LangGraph recursion
                         limit as a backstop          (agents/graph.step_limit)
    tool-call budget     AGENT_MAX_TOOL_CALLS searches per question
                                                      (agents/tools/registry.py)
    timeout              AGENT_TIMEOUT_S for the whole run (agents/graph.py)
    duplicate actions    a search already run is skipped; "nothing new" ends
                         retries                     (agents/retrieval_agent.py)
    permissions/tenant   per-tool Permission; tenant_id/role injected by the
                         registry, refused in arguments  (agents/tools/registry.py)

Argument limits (Phase 11, this module): the registry calls
`check_arguments` before every tool call, so a plan corrupted by text inside
a contract can't turn one tool call into an expensive or oversized request
(a 50 KB "query", limit=100000, thousands of ids). Unknown arguments are
refused too, so a tool can't be steered through parameters it never meant
to expose.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

MAX_QUERY_CHARS = 500
MAX_RESULTS = 100
MAX_IDS = 50


def _text(max_chars: int) -> Callable[[Any], str | None]:
    def check(value: Any) -> str | None:
        if not isinstance(value, str) or not value.strip():
            return "must be a non-empty string"
        return f"is longer than {max_chars} characters" if len(value) > max_chars else None

    return check


def _count(maximum: int) -> Callable[[Any], str | None]:
    def check(value: Any) -> str | None:
        if isinstance(value, bool) or not isinstance(value, int):
            return "must be an integer"
        return None if 1 <= value <= maximum else f"must be between 1 and {maximum}"

    return check


def _ids(maximum: int, *, optional: bool) -> Callable[[Any], str | None]:
    def check(value: Any) -> str | None:
        if value is None and optional:
            return None
        if not isinstance(value, list | tuple) or not all(isinstance(v, str) for v in value):
            return "must be a list of ids"
        return f"has more than {maximum} ids" if len(value) > maximum else None

    return check


# tool name -> argument name -> check (returns a problem, or None if fine)
ARGUMENT_RULES: dict[str, dict[str, Callable[[Any], str | None]]] = {
    "search_contracts": {
        "question": _text(MAX_QUERY_CHARS),
        "document_ids": _ids(MAX_IDS, optional=True),
        "version_ids": _ids(MAX_IDS, optional=True),
        "limit": _count(MAX_RESULTS),
    },
    "get_sections": {
        "parent_ids": _ids(MAX_IDS, optional=False),
    },
}


def check_arguments(tool: str, arguments: dict[str, Any]) -> str | None:
    """A description of the first problem with `arguments`, or None if they
    are acceptable. Tools without rules are not restricted here."""
    rules = ARGUMENT_RULES.get(tool)
    if rules is None:
        return None
    unknown = sorted(arguments.keys() - rules.keys())
    if unknown:
        return f"unexpected arguments {unknown}"
    for name, check in rules.items():
        problem = check(arguments.get(name))
        if problem:
            return f"'{name}' {problem}"
    return None
