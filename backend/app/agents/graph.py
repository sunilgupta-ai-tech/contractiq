"""
LangGraph workflow: understand -> select documents -> retrieve -> rerank -> extract
clauses -> validate evidence (retry/refine when insufficient) -> answer -> cite.

Status: interface placeholder — implemented in Phase 8.
"""

from __future__ import annotations


def build_graph(*args: object, **kwargs: object) -> object:
    raise NotImplementedError("Phase 8")
