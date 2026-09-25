"""
Rule-based risk analysis over LLM-extracted clauses (auto-renewal, missing
liability cap, uncapped indemnity, long notice periods, ...). Every clause
finding carries its evidence (page, clause, verified excerpt); output is
advisory.

    extraction (model)  ->  facts per topic  ->  RiskAgent rules  ->  findings

See agents/risk_agent.py for the rules and why they are rules.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict

from app.agents.risk_agent import SEVERITY_ORDER, RiskFinding
from app.schemas.analysis import RiskAnalysisRequest, RiskAnalysisResponse, RiskFindingOut
from app.services.contract_service import ContractService, analysis_errors, risk_counts


class RiskService:
    def __init__(self, contracts: ContractService) -> None:
        self.contracts = contracts

    async def analyze(self, request: RiskAnalysisRequest) -> RiskAnalysisResponse:
        pending: list[str] = []
        if request.version_id is not None:
            ref = await self.contracts.resolve_version(request.version_id)
            async with analysis_errors():
                analysis = await self.contracts.analyzer().clauses(ref)
            analysed = [(ref, analysis)]
        else:
            refs, not_ready = await self.contracts.current_versions(request.document_ids)
            analysed, pending = await self.contracts.analyses(refs)
            pending = [*pending, *not_ready]

        analyzer = self.contracts.analyzer()
        findings: list[RiskFinding] = []
        for ref, analysis in analysed:
            findings.extend(analyzer.findings(analysis, ref))
        findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.document_title or ""))
        return RiskAnalysisResponse(
            findings=[RiskFindingOut(**asdict(f)) for f in findings],
            counts=risk_counts(findings),
            documents_analyzed=len(analysed),
            pending_document_ids=[uuid.UUID(i) for i in pending],
        )
