"""
Build the evidence the LLM reads, from reranked search hits.

Small-to-big
------------
Search matches small child chunks (about one clause) because small chunks
match precisely. But a clause read alone can mislead: "8.3 ... subject to
clause 8.5" needs 8.5, and definitions often sit two clauses away. So each
hit is expanded to its parent section, which the LLM reads instead.

Steps:
  1. Group hits by parent section, keeping the best hit's rank order.
     (Two hits in the same section become ONE block — no duplicated text.)
  2. For each group, use the whole section if it fits the budget, otherwise
     fall back to just the matched chunks' text.
  3. Stop when the token budget is spent (the first block is always kept).
  4. Number the blocks [1], [2], ... — the numbers the answer cites.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.chunking.tokens import estimate_tokens
from app.rag.types import EvidenceBlock, RetrievedChunk


def build_evidence(
    ranked: list[RetrievedChunk], parents: Mapping[str, Any], *, max_tokens: int
) -> list[EvidenceBlock]:
    groups: dict[str, list[RetrievedChunk]] = {}
    for chunk in ranked:
        groups.setdefault(chunk.parent_id or chunk.chunk_id, []).append(chunk)

    blocks: list[EvidenceBlock] = []
    used = 0
    for key, matches in groups.items():
        parent = parents.get(key)
        matched_text = "\n\n".join(m.text for m in matches)
        options = [parent["text"], matched_text] if parent else [matched_text]
        remaining = max_tokens - used
        text = next((t for t in options if estimate_tokens(t) <= remaining), None)
        if text is None:
            if blocks:
                break  # budget spent; lower-ranked groups are dropped
            text = matched_text  # always keep the best evidence, even if large
        used += estimate_tokens(text)
        blocks.append(
            EvidenceBlock(
                number=len(blocks) + 1,
                text=text,
                heading=block_heading(matches[0]),
                matches=matches,
            )
        )
    return blocks


def block_heading(chunk: RetrievedChunk) -> str:
    """A one-line label shown above each block in the prompt, so the model
    knows which contract, version and page the text comes from, e.g.
    'Acme MSA > 8 TERMINATION > 8.3 Notice Period | version v2 | pages 12-13'."""
    path = " > ".join(chunk.heading_path) or (chunk.document_title or "Document")
    pages = (
        f"page {chunk.page}"
        if chunk.page == chunk.page_end
        else f"pages {chunk.page}-{chunk.page_end}"
    )
    return f"{path} | version {chunk.version_label} | {pages}"
