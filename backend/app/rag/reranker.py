"""
Reranking: reorder search candidates so the best evidence comes first, then
keep the top N for the prompt.

Why rerank after hybrid search
------------------------------
Fusion ranks by position in two lists; it doesn't know that a question
naming "clause 8.3" is almost certainly answered by the chunk *labelled* 8.3,
or that a heading ("Limitation of Liability") is stronger evidence than the
same words buried in a paragraph. The reranker adds that knowledge.

Implementations
---------------
* HeuristicReranker (default) — structural and lexical signals on top of the
  fused order. Fast, free, explainable, no extra dependencies.
* NoopReranker — keep the fused order (RERANKER=none), useful as an
  evaluation baseline (Phase 12).

A neural cross-encoder (e.g. bge-reranker) is deliberately not bundled: it
needs PyTorch (several GB in the image) and a GPU/CPU budget per query. The
`Reranker` protocol is the integration point if evaluation shows it is worth
it — e.g. a hosted rerank API — with no change to the rest of the pipeline.
"""

from __future__ import annotations

import re
from typing import Protocol

from app.rag.types import RetrievedChunk
from app.vectorstore.sparse import tokenize

# "8.3", "12.1.4", or "clause 8" / "section 8" / "article 8"
_DOTTED = re.compile(r"\b\d{1,3}(?:\.\d{1,3})+\b")
_NAMED = re.compile(r"\b(?:clause|section|article|paragraph)\s+(\d{1,3}(?:\.\d{1,3})*)\b", re.I)

# Weights of each signal. The fused order (`position`) stays the backbone;
# an explicit clause reference is the strongest override.
W_POSITION = 1.0
W_CLAUSE = 1.5
W_HEADING = 0.6
W_TEXT = 0.3


class Reranker(Protocol):
    name: str

    async def rerank(
        self, question: str, chunks: list[RetrievedChunk], top_n: int
    ) -> list[RetrievedChunk]: ...


class NoopReranker:
    name = "none"

    async def rerank(
        self, question: str, chunks: list[RetrievedChunk], top_n: int
    ) -> list[RetrievedChunk]:
        return chunks[:top_n]


def referenced_clauses(question: str) -> set[str]:
    """Clause numbers named in a question: 'clause 8.3 and 12' -> {'8.3', '12'}."""
    return set(_DOTTED.findall(question)) | {m.group(1) for m in _NAMED.finditer(question)}


class HeuristicReranker:
    name = "heuristic"

    async def rerank(
        self, question: str, chunks: list[RetrievedChunk], top_n: int
    ) -> list[RetrievedChunk]:
        if not chunks:
            return []
        clauses = referenced_clauses(question)
        terms = set(tokenize(question))
        count = len(chunks)
        for position, chunk in enumerate(chunks):
            score = W_POSITION * (1 - position / count)
            covered = {chunk.clause, chunk.section, *chunk.clauses}
            if clauses & covered:
                score += W_CLAUSE
            if terms:
                heading = set(tokenize(" ".join(chunk.heading_path)))
                body = set(tokenize(chunk.text))
                score += W_HEADING * len(terms & heading) / len(terms)
                score += W_TEXT * len(terms & body) / len(terms)
            chunk.rerank_score = round(score, 4)
        # sorted() is stable: equal scores keep the fused order.
        ranked = sorted(chunks, key=lambda c: c.rerank_score or 0.0, reverse=True)
        return ranked[:top_n]


def create_reranker(name: str) -> Reranker:
    """RERANKER setting -> implementation. Unknown names fail loudly at use."""
    rerankers: dict[str, Reranker] = {"heuristic": HeuristicReranker(), "none": NoopReranker()}
    if name not in rerankers:
        raise ValueError(f"Unknown RERANKER '{name}'; use one of {sorted(rerankers)}")
    return rerankers[name]
