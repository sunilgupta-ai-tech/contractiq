"""
The standard clauses ContractIQ extracts from every contract (Phase 10),
and the typed facts ("attributes") read from each.

Why a fixed list
----------------
Comparison, risk rules and portfolio views all need the *same* questions
answered for every contract: "is there a liability cap?", "how many days'
notice to terminate?". A fixed topic list with typed attributes turns each
contract into comparable data. Free-form "extract all clauses" output can't
be diffed, aggregated or checked by rules.

Each topic has a search query (written in contract vocabulary, used to
retrieve candidate chunks) and an attribute spec. Attribute values come
from the model and are *coerced* here to their declared type. A value that
doesn't fit ("sixty-ish", "2026-02-30") becomes None: a rule never runs on a
malformed fact.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

AttrType = Literal["int", "bool", "date", "str", "list"]


@dataclass(frozen=True)
class Topic:
    key: str
    label: str
    query: str  # retrieval query, in contract wording
    description: str  # what the model should look for
    attributes: dict[str, AttrType] = field(default_factory=dict)


TOPICS: tuple[Topic, ...] = (
    Topic(
        "parties",
        "Parties",
        "this agreement is made between the parties by and between",
        "who the contracting parties are (the preamble / parties clause)",
        {"parties": "list"},
    ),
    Topic(
        "term",
        "Term",
        "term of this agreement commencement effective date initial term expire",
        "when the contract starts and ends, and how long the initial term is",
        {"effective_date": "date", "expiry_date": "date", "initial_term_months": "int"},
    ),
    Topic(
        "auto_renewal",
        "Automatic renewal",
        "automatically renew successive renewal periods unless notice of non-renewal",
        "whether the contract renews automatically, for how long, and the notice needed to stop it",
        {"auto_renews": "bool", "renewal_term_months": "int", "non_renewal_notice_days": "int"},
    ),
    Topic(
        "termination_convenience",
        "Termination for convenience",
        "terminate for convenience without cause upon written notice",
        "whether a party may terminate without cause, which party, and the notice period",
        {"permitted": "bool", "notice_days": "int", "party": "str"},
    ),
    Topic(
        "termination_cause",
        "Termination for cause",
        "terminate for material breach not remedied cure period insolvency",
        "termination for breach or insolvency, including any cure period",
        {"cure_days": "int"},
    ),
    Topic(
        "liability_cap",
        "Limitation of liability",
        "limitation of liability aggregate liability shall not exceed cap consequential damages",
        "whether total liability is capped and what the cap is",
        {"capped": "bool", "cap": "str"},
    ),
    Topic(
        "indemnity",
        "Indemnity",
        "indemnify defend hold harmless against losses third-party claims",
        "who indemnifies whom, for what, and whether the indemnity is excluded from the cap",
        {"indemnifying_party": "str", "uncapped": "bool"},
    ),
    Topic(
        "payment_terms",
        "Payment terms",
        "invoices payable within days of receipt payment of fees late payment interest",
        "when invoices must be paid",
        {"payment_days": "int"},
    ),
    Topic(
        "price_change",
        "Price changes",
        "increase fees adjust prices annually price increase upon notice",
        "whether a party may change prices, the notice needed, and any cap on increases",
        {"unilateral": "bool", "notice_days": "int", "has_ceiling": "bool"},
    ),
    Topic(
        "confidentiality",
        "Confidentiality",
        "confidential information shall not disclose confidentiality obligations survive",
        "confidentiality obligations and how long they last",
        {"duration_years": "int"},
    ),
    Topic(
        "data_protection",
        "Data protection",
        "personal data processing sub-processors data protection laws controller processor",
        "personal-data obligations, including whether the customer may object to sub-processors",
        {"subprocessor_objection_right": "bool"},
    ),
    Topic(
        "assignment",
        "Assignment",
        "assign or transfer this agreement without prior written consent",
        "whether a party may assign the contract, and whether consent is required",
        {"consent_required": "bool"},
    ),
    Topic(
        "governing_law",
        "Governing law",
        "governed by and construed in accordance with the laws of",
        "which law governs the contract",
        {"law": "str"},
    ),
    Topic(
        "dispute_resolution",
        "Dispute resolution",
        "disputes arbitration mediation exclusive jurisdiction of the courts",
        "how disputes are resolved (courts, arbitration, escalation)",
        {"mechanism": "str"},
    ),
    Topic(
        "force_majeure",
        "Force majeure",
        "force majeure events beyond reasonable control",
        "relief for events beyond a party's control",
    ),
)
TOPICS_BY_KEY = {t.key: t for t in TOPICS}

_INT = re.compile(r"^\s*(\d{1,6})\b")
MAX_STR_CHARS = 200
MAX_LIST_ITEMS = 10


def coerce_attributes(spec: dict[str, AttrType], raw: Any) -> dict[str, Any]:
    """Keep only declared attributes, each converted to its type or None."""
    values = raw if isinstance(raw, dict) else {}
    return {name: _coerce(kind, values.get(name)) for name, kind in spec.items()}


def _coerce(kind: AttrType, value: Any) -> Any:
    if value is None:
        return None
    if kind == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in ("true", "yes"):
            return True
        if isinstance(value, str) and value.strip().lower() in ("false", "no"):
            return False
        return None
    if kind == "int":
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value if value >= 0 else None
        if isinstance(value, float) and value.is_integer() and value >= 0:
            return int(value)
        if isinstance(value, str) and (m := _INT.match(value)):
            return int(m.group(1))  # "60 days" -> 60
        return None
    if kind == "date":
        try:
            return date.fromisoformat(str(value).strip()[:10]).isoformat()
        except ValueError:
            return None
    if kind == "list":
        items = value if isinstance(value, list) else []
        clean = [" ".join(str(i).split())[:MAX_STR_CHARS] for i in items if str(i).strip()]
        return clean[:MAX_LIST_ITEMS] or None
    text = " ".join(str(value).split())[:MAX_STR_CHARS]
    return text or None
