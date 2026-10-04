"""
Choosing the evidence an answer may cite, when several documents say the same thing.

The reranker orders every candidate chunk; this module picks the top `top_n`
from that order with three rules. None of them calls a model, so they cost no
tokens, and the evidence budget (CONTEXT_MAX_TOKENS) is unchanged.

1. Repeated text is merged, and only repeated text. A chunk is dropped only when
   every word and number in it already appears, in the same order, inside a
   chunk that is kept (the same definition copied into five handbooks). Then it
   adds nothing, so nothing is lost: its document is recorded on the kept chunk
   as `also_found_in` and shown under the answer ("Also found in: …"). Anything
   that differs, even one amount, date, name or "not", keeps both: two invoices
   from one template are different evidence. The freed slots go to the next
   distinct evidence. When a lower-ranked chunk wholly contains a kept one (the
   same sentence inside a longer section), the longer chunk takes the kept one's
   slot and the shorter one's document moves to `also_found_in`.
2. One document can fill at most `max_per_document` slots while other documents
   have relevant evidence, so a long document cannot crowd out the rest. If
   there is nothing else, its remaining chunks fill the slots after all.
3. Exact ties go to the most recently uploaded document. Only chunks with the
   same score swap places, so a ranking without ties is unchanged; chunks
   indexed before `uploaded_at` existed simply keep their order.

With a single document and no duplicates the result is the reranker's top
`top_n`, exactly as before.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence

from app.rag.types import RetrievedChunk

_WORD = re.compile(r"\w+")


def _normalized(text: str) -> str:
    """Words and numbers only, lower-cased: layout, punctuation and spacing differ
    between copies of the same text, its content does not."""
    return " " + " ".join(_WORD.findall(text.lower())) + " "


def adds_nothing(text: str, kept: str) -> bool:
    """True when `text` is wholly contained in `kept`: every word and number, in
    order. Then dropping it loses no information. Any difference keeps it."""
    small = _normalized(text)
    return len(small) > 2 and small in _normalized(kept)


def _score(chunk: RetrievedChunk) -> float:
    return chunk.rerank_score if chunk.rerank_score is not None else chunk.score


def _newest_first_on_ties(ranked: Sequence[RetrievedChunk]) -> list[RetrievedChunk]:
    """Within each run of equal scores, newer uploads first; order is otherwise kept."""
    result: list[RetrievedChunk] = []
    run: list[RetrievedChunk] = []
    for chunk in ranked:
        if run and _score(chunk) != _score(run[0]):
            result += sorted(run, key=lambda c: c.uploaded_at or "", reverse=True)
            run = []
        run.append(chunk)
    result += sorted(run, key=lambda c: c.uploaded_at or "", reverse=True)
    return result


def select_evidence(
    ranked: Sequence[RetrievedChunk], top_n: int, *, max_per_document: int
) -> tuple[list[RetrievedChunk], int]:
    """The chunks to cite, in rank order, and how many duplicates were merged.

    `ranked` is the reranker's full order (best first), not just its top_n."""
    ordered = _newest_first_on_ties(ranked)
    position = {id(c): i for i, c in enumerate(ordered)}
    for chunk in ordered:
        chunk.also_found_in = []
    kept: list[RetrievedChunk] = []
    held_back: list[RetrievedChunk] = []  # over a document's share, used only if slots remain
    per_document: Counter[str] = Counter()
    merged = 0
    for chunk in ordered:
        original = next((k for k in kept + held_back if adds_nothing(chunk.text, k.text)), None)
        if original is not None:
            merged += 1
            _record(original, chunk)
            continue
        inner = next((k for k in kept if adds_nothing(k.text, chunk.text)), None)
        if inner is not None:
            # `chunk` says everything `inner` says and more: it takes inner's slot.
            merged += 1
            kept[kept.index(inner)] = chunk
            position[id(chunk)] = position[id(inner)]
            per_document[inner.document_id] -= 1
            per_document[chunk.document_id] += 1
            for other in inner.also_found_in:
                _record(chunk, other)
            _record(chunk, inner)
            continue
        if len(kept) >= top_n:
            continue  # still scanned, so later copies are recorded as "also found in"
        if per_document[chunk.document_id] >= max_per_document:
            held_back.append(chunk)
            continue
        kept.append(chunk)
        per_document[chunk.document_id] += 1
    # Nothing else relevant: a document's extra chunks fill the free slots.
    kept += held_back[: max(0, top_n - len(kept))]
    return sorted(kept, key=lambda c: position[id(c)]), merged


def _record(kept: RetrievedChunk, other: RetrievedChunk | dict[str, str | None]) -> None:
    """Note that `other`'s document also holds `kept`'s text (each document once)."""
    if isinstance(other, RetrievedChunk):
        other = {"document_id": other.document_id, "document_title": other.document_title}
    known = {kept.document_id} | {d["document_id"] for d in kept.also_found_in}
    if other["document_id"] not in known:
        kept.also_found_in.append(other)
