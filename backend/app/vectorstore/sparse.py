"""
Sparse (keyword) vectors for hybrid search.

Why keyword vectors next to embeddings
--------------------------------------
Dense embeddings match *meaning* ("end the agreement" ~ "terminate"), but
they are weak on exact tokens that matter enormously in contracts: clause
numbers ("8.3"), defined terms ("Service Credits"), amounts ("£5,000,000"),
party names. A keyword vector matches those exactly. Phase 7 searches both
and fuses the rankings.

How this implements BM25 on Qdrant
----------------------------------
BM25 scores a document by   sum over query terms of  IDF(term) * TF-part.
* TF-part is computed here, per chunk: tf * (k1 + 1) / (tf + k1). (Length
  normalisation, BM25's `b`, is omitted: chunks are already size-bounded.)
* IDF depends on the whole collection, so it cannot be computed per chunk.
  The collection's sparse vector is configured with `Modifier.IDF`, which
  makes Qdrant apply IDF at query time from its own term statistics.

Terms are mapped to integer indices by hashing (no vocabulary to store or
keep in sync). A 32-bit hash makes collisions between real terms negligible.
The SAME `sparse_vector()` must be used for queries (Phase 7), otherwise the
indices won't line up.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass

# Words too common to help ranking. Kept short on purpose: legal words like
# "shall", "not", "without" can matter ("shall not"), so they are kept.
STOPWORDS = frozenset(
    "a an and are as at be by for from has have in is it its of on or that the "
    "this to was were will with".split()
)
# Words, plus numbers with internal dots/commas so "8.3" and "5,000,000" stay
# one token (clause references and amounts are exactly what keyword search
# is for).
_TOKEN = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)*")
K1 = 1.2  # BM25 term-frequency saturation


@dataclass(frozen=True)
class SparseVector:
    indices: list[int]
    values: list[float]


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in STOPWORDS]


def term_index(term: str) -> int:
    """Stable 32-bit index for a term (blake2b: stable across processes,
    unlike Python's built-in hash(), which is randomised per process)."""
    return int.from_bytes(hashlib.blake2b(term.encode(), digest_size=4).digest(), "big")


def sparse_vector(text: str, *, query: bool = False) -> SparseVector:
    """BM25 term weights for a chunk, or plain term presence for a query.

    For a query, each term counts once (weight 1.0): Qdrant multiplies by IDF,
    and repeating a word in a question should not change the ranking.
    """
    counts = Counter(tokenize(text))
    weights: dict[int, float] = {}
    for term, tf in counts.items():
        index = term_index(term)
        weight = 1.0 if query else tf * (K1 + 1) / (tf + K1)
        # On the (very rare) hash collision, keep the larger weight.
        weights[index] = max(weights.get(index, 0.0), weight)
    ordered = sorted(weights)
    return SparseVector(indices=ordered, values=[round(weights[i], 4) for i in ordered])
