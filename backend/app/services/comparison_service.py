"""
Clause-aligned comparison across contracts and across versions/amendments of
one contract.

Both sides are analysed with the same clause topics (cached per version),
then aligned by topic — so renumbered clauses still line up, and two
different contracts can be compared at all. See agents/comparison_agent.py.
The right-hand side's risk flags mark rows whose change carries a risk.
"""

from __future__ import annotations

from dataclasses import asdict

from app.agents.comparison_agent import align
from app.core.exceptions import AppError, ErrorCode
from app.schemas.analysis import CompareRequest, CompareResponse, ComparisonRowOut, DiffCounts
from app.services.contract_service import ContractService, analysis_errors


class SameVersionError(AppError):
    status_code = 422
    code = ErrorCode.VALIDATION_ERROR
    message = "Choose two different versions to compare."


class ComparisonService:
    def __init__(self, contracts: ContractService) -> None:
        self.contracts = contracts

    async def compare(self, request: CompareRequest) -> CompareResponse:
        if request.left_version_id == request.right_version_id:
            raise SameVersionError()
        left = await self.contracts.resolve_version(request.left_version_id)
        right = await self.contracts.resolve_version(request.right_version_id)
        analyzer = self.contracts.analyzer()
        async with analysis_errors():
            left_analysis = await analyzer.clauses(left)
            right_analysis = await analyzer.clauses(right)

        rows = align(
            left_analysis.clauses,
            right_analysis.clauses,
            right_findings=analyzer.findings(right_analysis, right),
        )
        counts = DiffCounts()
        for row in rows:
            setattr(counts, row.diff.value, getattr(counts, row.diff.value) + 1)
        return CompareResponse(
            left=left.out(),
            right=right.out(),
            rows=[ComparisonRowOut(**asdict(row)) for row in rows],
            counts=counts,
        )
