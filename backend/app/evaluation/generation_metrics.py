"""
Answer-quality metrics for one golden example (Phase 12).

Deterministic metrics (always on; free, repeatable, CI-safe):

    fact_recall         share of expected facts found in the answer
    correct             fact_recall == 1 (every expected fact present)
    abstained           the system said "not found" (insufficient_evidence)
    abstention_correct  answerable -> did not abstain; unanswerable -> did
    citation_precision  share of citations pointing at a relevant chunk
    cited_relevant      at least one citation points at a relevant chunk
    groundedness        Phase 11's per-answer score (claims supported by
                        their cited evidence)

LLM-as-judge (optional, `--judge`): a model compares the answer with the
expected answer and returns correct / partially_correct / incorrect. It
catches what fact matching can't (an answer with the right number attached
to the wrong obligation) but costs a model call per example and varies
between judge models, so it complements, never replaces, the deterministic
metrics. The judge sees the question, the reference and the answer — never
the contract — and its JSON is validated like any other model output.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.agents.prompts import parse_json_object
from app.evaluation.dataset import GoldenExample, fact_found
from app.llm.base import ChatMessage, LLMProvider
from app.rag.pipelines.qa import generate_answer
from app.rag.types import Citation

JUDGE_SCORES = {"correct": 1.0, "partially_correct": 0.5, "incorrect": 0.0}

JUDGE_SYSTEM = """You grade answers to questions about a contract against a reference answer.
Judge only whether the answer states the same facts as the reference. Ignore style, length and
citation markers like [1]. Extra correct detail is fine; a wrong or missing key fact is not.
Reply with ONE JSON object and nothing else."""

JUDGE_PROMPT = """Question: {question}

Reference answer: {reference}

Answer to grade: {answer}

Reply with ONLY this JSON object:
{{"verdict": "correct" | "partially_correct" | "incorrect", "reason": "<one sentence>"}}"""


@dataclass
class AnswerScores:
    fact_recall: float | None  # None for unanswerable examples
    correct: bool | None
    abstained: bool
    abstention_correct: bool
    citation_precision: float | None  # None when there are no citations
    cited_relevant: bool
    groundedness: float | None
    missing_facts: list[str]
    judge_score: float | None = None
    judge_reason: str | None = None


def score_answer(
    example: GoldenExample,
    *,
    answer: str,
    abstained: bool,
    citations: list[Citation],
    relevant_chunk_ids: set[str],
    groundedness: float | None,
) -> AnswerScores:
    if example.answerable and not abstained:
        missing = [f for f in example.facts if not fact_found(f, answer)]
        recall = 1 - len(missing) / len(example.facts)
    elif example.answerable:
        missing, recall = list(example.facts), 0.0
    else:
        missing, recall = [], None
    relevant_hits = [c for c in citations if c.chunk_id in relevant_chunk_ids]
    return AnswerScores(
        fact_recall=round(recall, 3) if recall is not None else None,
        correct=(recall == 1.0) if recall is not None else None,
        abstained=abstained,
        abstention_correct=abstained != example.answerable,
        citation_precision=round(len(relevant_hits) / len(citations), 3) if citations else None,
        cited_relevant=bool(relevant_hits),
        groundedness=groundedness,
        missing_facts=missing,
    )


@dataclass
class JudgeVerdict:
    score: float | None  # None: the judge's reply was unusable
    reason: str


async def judge_answer(
    llm: LLMProvider, *, question: str, reference: str, answer: str
) -> JudgeVerdict:
    prompt = JUDGE_PROMPT.format(question=question, reference=reference, answer=answer)
    messages = [ChatMessage("system", JUDGE_SYSTEM), ChatMessage("user", prompt)]
    result = await generate_answer(llm, messages, max_tokens=200)
    data = parse_json_object(result.text) or {}
    verdict = data.get("verdict")
    raw_reason = data.get("reason")
    reason = raw_reason if isinstance(raw_reason, str) else ""
    if verdict not in JUDGE_SCORES:
        return JudgeVerdict(None, "unparseable judge reply")
    return JudgeVerdict(JUDGE_SCORES[verdict], " ".join(reason.split())[:300])
