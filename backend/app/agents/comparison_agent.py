"""
Aligns clauses across documents/versions for comparison (Phase 10).

Alignment is by *topic*, not by clause number: "8.3 Notice" in v1 may be
"9.2 Notice" in v2 after renumbering, and two different contracts rarely
share numbering at all. Both sides were extracted with the same topic list
(agents/clause_topics.py), so each topic lines up exactly.

Per topic:
    neither side found        -> no row
    one side only             -> "missing"   (added or removed)
    facts equal and wording
      >= SAME_SIMILARITY       -> "same"
    otherwise                 -> "changed", with a note naming each changed
                                 fact ("Notice days: 30 → 60"), or the wording
                                 similarity when only the wording changed

Notes are built from the extracted facts, not generated, so they can't
contradict the quotes shown next to them.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import StrEnum
from typing import Any

from app.agents.clause_agent import ExtractedClause
from app.agents.clause_topics import TOPICS
from app.agents.risk_agent import RiskFinding, Severity, worst

SAME_SIMILARITY = 0.97


class DiffKind(StrEnum):
    SAME = "same"
    CHANGED = "changed"
    MISSING = "missing"


@dataclass
class Side:
    clause: str | None
    page: int | None
    text: str  # the verified quote (or the clause's own text)
    summary: str | None
    attributes: dict[str, Any]
    regions: list[dict[str, object]]


@dataclass
class ComparisonRow:
    topic: str
    label: str
    diff: DiffKind
    note: str
    left: Side | None
    right: Side | None
    similarity: float | None = None  # wording similarity 0-1 when both sides exist
    risk: Severity | None = None  # worst right-side finding on this topic, if changed


def align(
    left: list[ExtractedClause],
    right: list[ExtractedClause],
    *,
    right_findings: list[RiskFinding] | None = None,
) -> list[ComparisonRow]:
    """Rows in topic order. `right_findings` (risk flags of the right-hand
    version) mark rows whose change introduces or keeps a risk."""
    lefts, rights = {c.topic: c for c in left}, {c.topic: c for c in right}
    rows = []
    for topic in TOPICS:
        a, b = lefts.get(topic.key), rights.get(topic.key)
        a = a if a and a.found else None
        b = b if b and b.found else None
        if a is None and b is None:
            continue
        row = _row(topic.key, topic.label, a, b)
        if row.diff is not DiffKind.SAME and right_findings:
            row.risk = worst([f for f in right_findings if f.topic == topic.key])
        rows.append(row)
    return rows


def _row(
    topic: str, label: str, a: ExtractedClause | None, b: ExtractedClause | None
) -> ComparisonRow:
    left, right = _side(a), _side(b)
    if a is None or b is None:
        note = (
            f"{label} appears only in the right-hand document."
            if a is None
            else (f"{label} appears only in the left-hand document.")
        )
        return ComparisonRow(topic, label, DiffKind.MISSING, note, left, right)

    similarity = round(SequenceMatcher(None, _words(_text(a)), _words(_text(b))).ratio(), 3)
    changes = _fact_changes(a.attributes, b.attributes)
    if not changes and similarity >= SAME_SIMILARITY:
        return ComparisonRow(topic, label, DiffKind.SAME, "No change.", left, right, similarity)
    note = "; ".join(changes) + "." if changes else f"Wording changed ({similarity:.0%} similar)."
    return ComparisonRow(topic, label, DiffKind.CHANGED, note, left, right, similarity)


def _side(clause: ExtractedClause | None) -> Side | None:
    if clause is None:
        return None
    chunk = clause.chunk
    return Side(
        clause=clause.clause,
        page=clause.page,
        text=clause.quote or "",
        summary=clause.summary,
        attributes=clause.attributes,
        regions=chunk.regions if chunk else [],
    )


def _text(clause: ExtractedClause) -> str:
    """Compare whole clause text where available: two model-chosen quotes of
    the same clause can differ in length even when nothing changed."""
    return (clause.evidence or {}).get("text") or clause.quote or ""


def _words(text: str) -> list[str]:
    return text.lower().split()


def _fact_changes(left: dict[str, Any], right: dict[str, Any]) -> list[str]:
    """'Notice days: 30 → 60' for each fact stated on both sides that differs;
    'Capped: added (yes)' / 'removed' when stated on one side only."""
    changes = []
    for name in dict.fromkeys([*left, *right]):
        a, b = left.get(name), right.get(name)
        if a == b or (a is None and b is None):
            continue
        field = name.replace("_", " ").capitalize()
        if a is None:
            changes.append(f"{field}: now {_fmt(b)}")
        elif b is None:
            changes.append(f"{field}: no longer stated (was {_fmt(a)})")
        else:
            changes.append(f"{field}: {_fmt(a)} → {_fmt(b)}")
    return changes


def _fmt(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)
