"""
Tool registry: the only way agent nodes reach data.

Every tool call goes through `ToolRegistry.call()`, which enforces, in code
(never by asking the model):

1. Permission — each tool declares the Permission it needs; the caller's
   role (from the signed token, stored in state) must have it.
2. Tenant injection — `tenant_id` is taken from state and passed to the tool
   by the registry. Arguments may NOT contain `tenant_id` (or `role`); a call
   that tries is refused. So even a model that has been manipulated by text
   inside a contract cannot point a search at another organization.
3. Budget — at most `max_calls` tool calls per question, across all retries,
   so a looping workflow can't run up unbounded search/embedding costs.

Refusals raise ToolError; the graph turns them into a safe "not found"
answer and logs them, rather than surfacing internals.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.core.logging import get_logger
from app.core.security import Permission, Role, has_permission

logger = get_logger(__name__)

# Arguments only the registry may supply.
RESERVED_ARGS = frozenset({"tenant_id", "role"})

ToolFunc = Callable[..., Awaitable[Any]]


class ToolError(Exception):
    """A tool call was refused (permission, reserved argument, budget, unknown tool)."""


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    permission: Permission
    func: ToolFunc  # called as func(tenant_id=..., **arguments)


class ToolRegistry:
    def __init__(self, tools: list[Tool], *, max_calls: int) -> None:
        self._tools = {t.name: t for t in tools}
        self.max_calls = max_calls

    @property
    def names(self) -> list[str]:
        return sorted(self._tools)

    async def call(
        self,
        name: str,
        *,
        tenant_id: str,
        role: Role,
        calls_so_far: int,
        arguments: dict[str, Any],
    ) -> Any:
        """Run tool `name` for this tenant, or raise ToolError.

        `tenant_id`/`role` come from agent state (set by the API), never from
        `arguments`.
        """
        tool = self._tools.get(name)
        if tool is None:
            raise ToolError(f"Unknown tool '{name}'")
        forbidden = RESERVED_ARGS & arguments.keys()
        if forbidden:
            # ("args" is a reserved LogRecord attribute, hence "arguments".)
            logger.warning(
                "tool_reserved_argument", extra={"tool": name, "arguments": sorted(forbidden)}
            )
            raise ToolError(f"Tool arguments may not set {sorted(forbidden)}")
        if not has_permission(role, tool.permission):
            raise ToolError(f"Role {role.value} may not use '{name}'")
        if calls_so_far >= self.max_calls:
            raise ToolError(f"Tool-call budget of {self.max_calls} exhausted")
        return await tool.func(tenant_id=tenant_id, **arguments)
