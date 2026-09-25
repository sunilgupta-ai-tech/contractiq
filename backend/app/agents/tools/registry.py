"""
Tool registry. Each tool declares the Permission it needs; the registry checks the
caller's role before execution and injects tenant_id from state — tools never accept
tenant_id from the model.

Status: interface placeholder — implemented in Phase 8.
"""

from __future__ import annotations


class ToolRegistry:
    """See module docstring. Implemented in Phase 8."""
