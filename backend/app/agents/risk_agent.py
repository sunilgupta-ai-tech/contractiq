"""
Applies risk rules to extracted clauses (Phase 10). Output is advisory.

Rules, not a model's opinion
----------------------------
The model's job ends at extraction: it reads the contract and reports facts
("auto_renews: true, non_renewal_notice_days: 90"), each tied to a verified
quote. Deciding what is *risky* is done here by explicit, reviewable rules
over those facts. The same contract therefore always gets the same flags,
every flag explains itself, and legal teams can tune thresholds
(RISK_* settings) instead of prompts.

Two kinds of finding:
  * clause findings  cite the clause that triggered them (page, excerpt)
  * missing findings  a protective clause was not found (e.g. no liability
                      cap). They cite nothing, and are only raised when the
                      topic was actually searched without error.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from app.agents.clause_agent import ExtractedClause
from app.core.config import Settings

FINDING_NAMESPACE = uuid.UUID("0f6f3c1e-8d7b-4e61-a2d4-3c9b5e7f1a20")


class Severity(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


SEVERITY_ORDER = {Severity.HIGH: 0, Severity.MEDIUM: 1, Severity.LOW: 2}


@dataclass
class RiskFinding:
    id: str  # deterministic per (version, rule): stable across re-runs
    rule: str
    title: str
    severity: Severity
    topic: str
    rationale: str
    missing: bool  # True: a protective clause was not found (no excerpt)
    document_id: str
    document_title: str | None
    version_id: str
    version_label: str
    clause: str | None = None
    page: int | None = None
    excerpt: str | None = None
    regions: list[dict[str, object]] | None = None


@dataclass(frozen=True)
class VersionInfo:
    document_id: str
    document_title: str | None
    version_id: str
    version_label: str


@dataclass(frozen=True)
class _Hit:
    rule: str
    title: str
    severity: Severity
    topic: str
    rationale: str
    missing: bool = False


Clauses = dict[str, ExtractedClause]
Rule = Callable[[Clauses, Settings], _Hit | None]


def _attr(clauses: Clauses, topic: str, name: str) -> object:
    clause = clauses.get(topic)
    return clause.attributes.get(name) if clause and clause.found else None


def _found(clauses: Clauses, topic: str) -> bool:
    clause = clauses.get(topic)
    return bool(clause and clause.found)


def _searched_and_absent(clauses: Clauses, topic: str) -> bool:
    """Absent only if the topic was searched successfully and not found."""
    clause = clauses.get(topic)
    return clause is not None and not clause.found and not clause.error


def _days(value: object) -> str:
    return f"{value} days" if value is not None else "an unstated period"


# --- Rules -----------------------------------------------------------------------------


def no_liability_cap(c: Clauses, s: Settings) -> _Hit | None:
    if _searched_and_absent(c, "liability_cap"):
        return _Hit(
            "no_liability_cap",
            "No limitation of liability",
            Severity.HIGH,
            "liability_cap",
            "No clause limiting either party's total liability was found, so exposure may be "
            "unlimited.",
            missing=True,
        )
    return None


def uncapped_liability(c: Clauses, s: Settings) -> _Hit | None:
    if _attr(c, "liability_cap", "capped") is False:
        return _Hit(
            "uncapped_liability",
            "Liability is not capped",
            Severity.HIGH,
            "liability_cap",
            "The limitation-of-liability clause does not set an overall cap.",
        )
    return None


def uncapped_indemnity(c: Clauses, s: Settings) -> _Hit | None:
    if _attr(c, "indemnity", "uncapped") is True:
        party = _attr(c, "indemnity", "indemnifying_party")
        who = f" given by {party}" if party else ""
        return _Hit(
            "uncapped_indemnity",
            "Uncapped indemnity",
            Severity.HIGH,
            "indemnity",
            f"The indemnity{who} is unlimited or excluded from the liability cap.",
        )
    return None


def automatic_renewal(c: Clauses, s: Settings) -> _Hit | None:
    if _attr(c, "auto_renewal", "auto_renews") is True:
        term = _attr(c, "auto_renewal", "renewal_term_months")
        notice = _attr(c, "auto_renewal", "non_renewal_notice_days")
        period = f"for {term}-month periods " if term else ""
        return _Hit(
            "automatic_renewal",
            "Automatic renewal",
            Severity.MEDIUM,
            "auto_renewal",
            f"The contract renews automatically {period}unless notice is given "
            f"{_days(notice)} in advance; a missed deadline locks in another term.",
        )
    return None


def long_termination_notice(c: Clauses, s: Settings) -> _Hit | None:
    days = _attr(c, "termination_convenience", "notice_days")
    if isinstance(days, int) and days > s.risk_max_notice_days:
        return _Hit(
            "long_termination_notice",
            "Long termination notice",
            Severity.MEDIUM,
            "termination_convenience",
            f"Terminating for convenience requires {days} days' notice "
            f"(policy threshold: {s.risk_max_notice_days}).",
        )
    return None


def no_termination_for_convenience(c: Clauses, s: Settings) -> _Hit | None:
    if _attr(c, "termination_convenience", "permitted") is False or _searched_and_absent(
        c, "termination_convenience"
    ):
        return _Hit(
            "no_termination_for_convenience",
            "No termination for convenience",
            Severity.LOW,
            "termination_convenience",
            "No right to end the contract without cause was found; exit may require proving "
            "a breach.",
            missing=not _found(c, "termination_convenience"),
        )
    return None


def unilateral_price_change(c: Clauses, s: Settings) -> _Hit | None:
    if (
        _attr(c, "price_change", "unilateral") is True
        and _attr(c, "price_change", "has_ceiling") is not True
    ):
        return _Hit(
            "unilateral_price_change",
            "Unilateral price change",
            Severity.MEDIUM,
            "price_change",
            "One party may raise prices without an agreed ceiling on increases.",
        )
    return None


def no_subprocessor_objection(c: Clauses, s: Settings) -> _Hit | None:
    if _attr(c, "data_protection", "subprocessor_objection_right") is False:
        return _Hit(
            "no_subprocessor_objection",
            "No right to object to sub-processors",
            Severity.MEDIUM,
            "data_protection",
            "New sub-processors may be engaged without a right to object.",
        )
    return None


def long_payment_terms(c: Clauses, s: Settings) -> _Hit | None:
    days = _attr(c, "payment_terms", "payment_days")
    if isinstance(days, int) and days > s.risk_max_payment_days:
        return _Hit(
            "long_payment_terms",
            "Long payment terms",
            Severity.LOW,
            "payment_terms",
            f"Invoices are payable within {days} days "
            f"(policy threshold: {s.risk_max_payment_days}).",
        )
    return None


def free_assignment(c: Clauses, s: Settings) -> _Hit | None:
    if _attr(c, "assignment", "consent_required") is False:
        return _Hit(
            "free_assignment",
            "Assignment without consent",
            Severity.LOW,
            "assignment",
            "The contract may be transferred to another party without consent.",
        )
    return None


def no_confidentiality(c: Clauses, s: Settings) -> _Hit | None:
    if _searched_and_absent(c, "confidentiality"):
        return _Hit(
            "no_confidentiality",
            "No confidentiality clause",
            Severity.LOW,
            "confidentiality",
            "No confidentiality obligations were found.",
            missing=True,
        )
    return None


def foreign_governing_law(c: Clauses, s: Settings) -> _Hit | None:
    law = _attr(c, "governing_law", "law")
    home = (s.risk_home_jurisdiction or "").strip()
    if home and isinstance(law, str) and home.lower() not in law.lower():
        return _Hit(
            "foreign_governing_law",
            "Foreign governing law",
            Severity.LOW,
            "governing_law",
            f"Governed by {law}, not the organisation's default ({home}); consider "
            "enforcement costs.",
        )
    return None


RULES: tuple[Rule, ...] = (
    no_liability_cap,
    uncapped_liability,
    uncapped_indemnity,
    automatic_renewal,
    long_termination_notice,
    no_termination_for_convenience,
    unilateral_price_change,
    no_subprocessor_objection,
    long_payment_terms,
    free_assignment,
    no_confidentiality,
    foreign_governing_law,
)


class RiskAgent:
    def __init__(self, settings: Settings, rules: tuple[Rule, ...] = RULES) -> None:
        self.settings = settings
        self.rules = rules

    def assess(self, clauses: list[ExtractedClause], version: VersionInfo) -> list[RiskFinding]:
        """Findings for one version, most severe first."""
        by_topic = {c.topic: c for c in clauses}
        findings = []
        for rule in self.rules:
            hit = rule(by_topic, self.settings)
            if hit is None:
                continue
            clause = by_topic.get(hit.topic)
            chunk = clause.chunk if clause and clause.found and not hit.missing else None
            findings.append(
                RiskFinding(
                    id=str(uuid.uuid5(FINDING_NAMESPACE, f"{version.version_id}:{hit.rule}")),
                    rule=hit.rule,
                    title=hit.title,
                    severity=hit.severity,
                    topic=hit.topic,
                    rationale=hit.rationale,
                    missing=hit.missing,
                    document_id=version.document_id,
                    document_title=version.document_title,
                    version_id=version.version_id,
                    version_label=version.version_label,
                    clause=chunk.clause if chunk else None,
                    page=chunk.page if chunk else None,
                    excerpt=clause.quote if chunk and clause else None,
                    regions=chunk.regions if chunk else None,
                )
            )
        findings.sort(key=lambda f: SEVERITY_ORDER[f.severity])
        return findings


def worst(findings: list[RiskFinding]) -> Severity | None:
    if not findings:
        return None
    return min((f.severity for f in findings), key=SEVERITY_ORDER.__getitem__)
