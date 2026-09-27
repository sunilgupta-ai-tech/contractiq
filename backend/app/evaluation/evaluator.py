"""
Runs a pipeline configuration over a golden dataset (Phase 12).

For every example:

    1. retrieval   hybrid search for the question, scoped to its document's
                   version, then rerank. Relevant chunks are all indexed
                   chunks matching the example's evidence specs, so recall
                   has a true denominator.
    2. answer      the real Q&A path ("fast" pipeline or the "agent"), with
                   the same prompts, citation checks and groundedness report
                   users get
    3. score       retrieval metrics (Recall/Hit@k, MRR, nDCG), answer
                   metrics (facts, abstention, citations, groundedness) and,
                   optionally, an LLM judge

Results aggregate into one flat {metric: value} dict (what CI gates and
EvaluationRun.metrics store), plus a grounding calibration table: for each
candidate GROUNDING_MIN_SCORE, how many correct and incorrect answers
`enforce` mode would have withheld. That is the evidence for choosing the
threshold (and whether to enforce at all).

The evaluator has no database or network code of its own: search, reranker
and model are injected, so it runs against the real stack (CLI) or fakes
(tests) alike.
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from app.core.config import Settings
from app.core.security import SYSTEM_ROLE_PERMISSIONS, Permission, SystemRole
from app.evaluation import retrieval_metrics as rm
from app.evaluation.dataset import GoldenDataset, GoldenExample
from app.evaluation.generation_metrics import AnswerScores, judge_answer, score_answer
from app.evaluation.ingest import IngestedDocument
from app.llm.base import LLMProvider
from app.rag.pipelines.qa import QAPipeline, RagAnswer
from app.rag.reranker import Reranker
from app.rag.retriever import Retriever

K_VALUES = (1, 3, 5, 10)
CALIBRATION_THRESHOLDS = (0.25, 0.5, 0.75, 1.0)


@dataclass
class ExampleResult:
    id: str
    question: str
    answerable: bool
    tags: list[str]
    relevant_chunks: int
    retrieved: list[str]  # reranked chunk ids, best first
    retrieval: dict[str, float]
    answer: str
    citations: list[dict[str, Any]]
    scores: AnswerScores
    unsupported_claims: list[str]
    latency_ms: float
    prompt_tokens: int | None
    completion_tokens: int | None


@dataclass
class EvaluationReport:
    dataset: str
    dataset_version: int
    config: dict[str, Any]
    metrics: dict[str, float]
    calibration: list[dict[str, float]]
    examples: list[ExampleResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Evaluator:
    def __init__(
        self,
        *,
        retriever: Retriever,
        reranker: Reranker,
        llm: LLMProvider,
        settings: Settings,
        mode: str = "fast",
        judge: LLMProvider | None = None,
        permissions: frozenset[Permission] = SYSTEM_ROLE_PERMISSIONS[SystemRole.EMPLOYEE],
    ) -> None:
        if mode not in ("fast", "agent"):
            raise ValueError("mode must be 'fast' or 'agent'")
        self.retriever = retriever
        self.reranker = reranker
        self.llm = llm
        self.settings = settings
        self.mode = mode
        self.judge = judge
        self.permissions = permissions

    async def run(
        self,
        dataset: GoldenDataset,
        *,
        tenant_id: str,
        documents: dict[str, IngestedDocument],
        config: dict[str, Any] | None = None,
    ) -> EvaluationReport:
        results, warnings = [], []
        for example in dataset.examples:
            doc = documents[example.document]
            result = await self._run_example(example, doc, tenant_id)
            if example.answerable and result.relevant_chunks == 0:
                warnings.append(f"{example.id}: evidence matches no indexed chunk")
            results.append(result)
        return EvaluationReport(
            dataset=dataset.name,
            dataset_version=dataset.version,
            config={"mode": self.mode, **(config or {})},
            metrics=aggregate(results, judged=self.judge is not None),
            calibration=calibration(results),
            examples=results,
            warnings=warnings,
        )

    async def _run_example(
        self, example: GoldenExample, doc: IngestedDocument, tenant_id: str
    ) -> ExampleResult:
        relevant = {
            c.id
            for c in doc.children
            if any(
                spec.matches(
                    text=c.text,
                    clause=c.clause,
                    clauses=c.clauses,
                    page_start=c.page_start,
                    page_end=c.page_end,
                )
                for spec in example.evidence
            )
        }

        candidates = await self.retriever.retrieve(
            example.question,
            tenant_id=tenant_id,
            document_ids=None,
            version_ids=[doc.version_id],
            limit=self.settings.retrieval_candidates,
        )
        fused_ids = [c.chunk_id for c in candidates]
        reranked = await self.reranker.rerank(example.question, list(candidates), max(K_VALUES))
        ranked_ids = [c.chunk_id for c in reranked]
        retrieval = retrieval_scores(ranked_ids, fused_ids, relevant) if relevant else {}

        started = time.perf_counter()
        answer = await self._answer(example.question, tenant_id, doc.version_id)
        latency_ms = round((time.perf_counter() - started) * 1000, 1)

        grounding = answer.grounding
        scores = score_answer(
            example,
            answer=answer.answer,
            abstained=answer.insufficient_evidence,
            citations=answer.citations,
            relevant_chunk_ids=relevant,
            groundedness=grounding.score if grounding else None,
        )
        if self.judge is not None and example.answerable and not answer.insufficient_evidence:
            verdict = await judge_answer(
                self.judge,
                question=example.question,
                reference=example.expected_answer,
                answer=answer.answer,
            )
            scores.judge_score, scores.judge_reason = verdict.score, verdict.reason

        return ExampleResult(
            id=example.id,
            question=example.question,
            answerable=example.answerable,
            tags=list(example.tags),
            relevant_chunks=len(relevant),
            retrieved=ranked_ids,
            retrieval=retrieval,
            answer=answer.answer,
            citations=[
                {"index": c.index, "chunk_id": c.chunk_id, "clause": c.clause, "page": c.page}
                for c in answer.citations
            ],
            scores=scores,
            unsupported_claims=[c.sentence for c in grounding.unsupported] if grounding else [],
            latency_ms=latency_ms,
            prompt_tokens=answer.prompt_tokens,
            completion_tokens=answer.completion_tokens,
        )

    async def _answer(self, question: str, tenant_id: str, version_id: str) -> RagAnswer:
        if self.mode == "agent":
            from app.agents.graph import AgentRunner  # LangGraph only when needed

            runner = AgentRunner(self.retriever, self.reranker, self.llm, self.settings)
            return await runner.answer(
                question,
                tenant_id=tenant_id,
                permissions=self.permissions,
                version_ids=[version_id],
            )
        pipeline = QAPipeline(self.retriever, self.reranker, self.llm, self.settings)
        return await pipeline.answer(question, tenant_id=tenant_id, version_ids=[version_id])


# --- Scoring and aggregation --------------------------------------------------------------


def retrieval_scores(
    ranked: Sequence[str], fused: Sequence[str], relevant: set[str]
) -> dict[str, float]:
    scores = {f"recall@{k}": rm.recall_at_k(ranked, relevant, k) for k in K_VALUES}
    scores |= {f"hit@{k}": rm.hit_rate_at_k(ranked, relevant, k) for k in K_VALUES}
    scores["mrr"] = rm.reciprocal_rank(ranked, relevant)
    scores["ndcg@5"] = rm.ndcg_at_k(ranked, relevant, 5)
    # Before reranking: shows whether the reranker helps or hurts.
    scores["fused_recall@10"] = rm.recall_at_k(fused, relevant, 10)
    scores["fused_mrr"] = rm.reciprocal_rank(fused, relevant)
    return scores


def aggregate(results: Sequence[ExampleResult], *, judged: bool = False) -> dict[str, float]:
    answerable = [r for r in results if r.answerable]
    unanswerable = [r for r in results if not r.answerable]
    answered = [r for r in answerable if not r.scores.abstained]
    metrics: dict[str, float] = {}

    retrieval_keys = sorted({k for r in answerable for k in r.retrieval})
    for key in retrieval_keys:
        metrics[f"retrieval.{key}"] = rm.mean([r.retrieval[key] for r in answerable if r.retrieval])

    def share(items: Sequence[ExampleResult], pred: Any) -> float:
        return sum(1 for r in items if pred(r)) / len(items) if items else 0.0

    metrics["answer.accuracy"] = share(answerable, lambda r: r.scores.correct)
    metrics["answer.fact_recall"] = rm.mean([r.scores.fact_recall or 0.0 for r in answerable])
    metrics["answer.false_abstention_rate"] = share(answerable, lambda r: r.scores.abstained)
    metrics["answer.abstention_accuracy"] = share(unanswerable, lambda r: r.scores.abstained)
    metrics["citations.precision"] = rm.mean(
        [r.scores.citation_precision for r in answered if r.scores.citation_precision is not None]
    )
    metrics["citations.relevant_rate"] = share(answered, lambda r: r.scores.cited_relevant)
    metrics["grounding.mean"] = rm.mean(
        [r.scores.groundedness for r in answered if r.scores.groundedness is not None]
    )
    if judged:
        metrics["judge.score"] = rm.mean(
            [r.scores.judge_score for r in answered if r.scores.judge_score is not None]
        )
    latencies = sorted(r.latency_ms for r in results)
    if latencies:
        metrics["latency.p50_ms"] = statistics.median(latencies)
        metrics["latency.p95_ms"] = latencies[min(len(latencies) - 1, int(0.95 * len(latencies)))]
    metrics["examples"] = float(len(results))
    return {k: round(v, 4) for k, v in metrics.items()}


def calibration(results: Sequence[ExampleResult]) -> list[dict[str, float]]:
    """What GROUNDING_MODE=enforce would withhold at each threshold, among
    answered answerable examples: ideally many incorrect, few correct."""
    answered = [
        r
        for r in results
        if r.answerable and not r.scores.abstained and r.scores.groundedness is not None
    ]
    rows = []
    for threshold in CALIBRATION_THRESHOLDS:
        withheld = [r for r in answered if (r.scores.groundedness or 0.0) < threshold]
        shown = [r for r in answered if r not in withheld]
        rows.append(
            {
                "threshold": threshold,
                "withheld": len(withheld),
                "withheld_correct": sum(1 for r in withheld if r.scores.correct),
                "withheld_incorrect": sum(1 for r in withheld if not r.scores.correct),
                "shown_accuracy": round(sum(1 for r in shown if r.scores.correct) / len(shown), 4)
                if shown
                else 0.0,
            }
        )
    return rows
