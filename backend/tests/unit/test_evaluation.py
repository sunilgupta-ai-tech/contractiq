"""
Phase 12 tests: golden dataset (format, validation, and consistency with the
real parser + chunker), fact and evidence matching, answer scoring, the LLM
judge, aggregation and grounding calibration, the regression gate and
reports, and a full evaluator run over the sample contract with fakes.
"""

import json
import re

import pytest

from app.core.config import Settings
from app.evaluation import __main__ as cli
from app.evaluation.dataset import (
    DATASETS_DIR,
    EvidenceSpec,
    GoldenDataset,
    GoldenExample,
    fact_found,
)
from app.evaluation.evaluator import (
    EvaluationReport,
    Evaluator,
    ExampleResult,
    aggregate,
    calibration,
)
from app.evaluation.generation_metrics import AnswerScores, judge_answer, score_answer
from app.evaluation.ingest import IngestedDocument
from app.evaluation.report import compare_to_baseline, load_baseline, render_markdown, write_reports
from app.evaluation.sample_contract import sample_msa_pdf
from app.llm.base import LLMResult
from app.rag.reranker import HeuristicReranker
from app.rag.types import Citation, RetrievedChunk
from app.services.chunking_service import ChunkingOptions, chunk_document
from app.services.pdf_service import PdfOptions, finalize_layout, parse_pdf
from app.vectorstore.sparse import tokenize
from tests.unit.test_rag import FakeLLM

SAMPLE = DATASETS_DIR / "sample_msa.json"


@pytest.fixture(scope="module")
def sample_chunks():
    parsed = parse_pdf(sample_msa_pdf(), PdfOptions())
    finalize_layout(parsed.document)
    return chunk_document(
        parsed.document, version_id="v1", document_title="MSA", options=ChunkingOptions()
    ).children


# --- Dataset ---------------------------------------------------------------------------------


def test_builtin_dataset_loads():
    dataset = GoldenDataset.load(SAMPLE)
    assert dataset.name == "sample-msa" and len(dataset.examples) == 27
    assert sum(not ex.answerable for ex in dataset.examples) == 4


def test_every_answerable_example_is_findable_in_the_real_chunks(sample_chunks):
    """Guards the dataset against parser/chunker changes: each example's
    evidence must match an indexed chunk, and that chunk must contain the
    expected facts. If this fails, fix the dataset or the regression."""
    dataset = GoldenDataset.load(SAMPLE)
    for ex in (e for e in dataset.examples if e.answerable):
        relevant = [
            c
            for c in sample_chunks
            if any(
                s.matches(
                    text=c.text,
                    clause=c.clause,
                    clauses=c.clauses,
                    page_start=c.page_start,
                    page_end=c.page_end,
                )
                for s in ex.evidence
            )
        ]
        assert relevant, ex.id
        text = " ".join(c.text for c in relevant)
        assert all(fact_found(f, text) for f in ex.facts), ex.id


def _dataset(**example):
    base = {
        "id": "q",
        "document": "d",
        "question": "?",
        "facts": ["x"],
        "evidence": [{"clause": "1"}],
    }
    return {
        "name": "t",
        "documents": {"d": {"title": "T", "builder": "sample_msa"}},
        "examples": [base | example],
    }


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"document": "missing"}, "unknown document"),
        ({"facts": []}, "need facts and evidence"),
        ({"answerable": False}, "have no facts or evidence"),
    ],
)
def test_malformed_datasets_are_rejected(change, message):
    with pytest.raises(ValueError, match=message):
        GoldenDataset.from_dict(_dataset(**change))


def test_duplicate_ids_and_ambiguous_sources_are_rejected():
    data = _dataset()
    data["examples"].append(dict(data["examples"][0]))
    with pytest.raises(ValueError, match="unique"):
        GoldenDataset.from_dict(data)
    data = _dataset()
    data["documents"]["d"]["path"] = "x.pdf"
    with pytest.raises(ValueError, match="exactly one of builder/path"):
        GoldenDataset.from_dict(data)


@pytest.mark.parametrize(
    ("fact", "answer", "found"),
    [
        ("90|ninety", "Notice of Ninety days", True),
        ("5%", "a credit of 5% per 0.1%", True),
        ("5", "within 15 days", False),  # whole numbers only
        ("5", "up to 25%", False),
        ("5", "5.5 hours", False),
        ("1.5%", "interest of 1.5% per month", True),
        ("3,000,000", "INR 3000000", True),
        ("3000000", "INR 3,000,000", True),
        ("intellectual property", "Intellectual  Property rights", True),
        ("Mumbai", "arbitration in Delhi", False),
    ],
)
def test_fact_matching(fact, answer, found):
    assert fact_found(fact, answer) is found


def test_evidence_spec_fields_are_all_required():
    spec = EvidenceSpec(clause="3.1", text="ninety")
    kw = {"page_start": 1, "page_end": 1}
    assert spec.matches(text="... ninety (90) days", clause="3.1", clauses=["3.1"], **kw)
    assert spec.matches(text="... ninety (90) days", clause="3", clauses=["3.1", "3.2"], **kw)
    assert not spec.matches(text="... thirty days", clause="3.1", clauses=["3.1"], **kw)
    assert not EvidenceSpec(page=2).matches(text="", clause=None, clauses=[], **kw)


# --- Answer scoring --------------------------------------------------------------------------


EXAMPLE = GoldenExample(
    id="n",
    document="d",
    question="notice?",
    facts=("90|ninety", "12"),
    evidence=(EvidenceSpec(clause="3.1"),),
)
UNANSWERABLE = GoldenExample(id="u", document="d", question="insurance?", answerable=False)


def _citation(chunk_id):
    return Citation(
        index=1,
        chunk_id=chunk_id,
        document_id="d",
        document_title="T",
        version_id="v",
        version_label="v1",
        page=1,
        page_end=1,
        section=None,
        section_title=None,
        clause=None,
        clause_title=None,
        quote="",
        score=1.0,
    )


def test_scores_for_correct_partial_and_abstained_answers():
    full = score_answer(
        EXAMPLE,
        answer="90 days before each 12-month term [1].",
        abstained=False,
        citations=[_citation("c1"), _citation("c9")],
        relevant_chunk_ids={"c1"},
        groundedness=1.0,
    )
    assert full.correct and full.fact_recall == 1.0 and full.citation_precision == 0.5
    assert full.cited_relevant and full.abstention_correct

    partial = score_answer(
        EXAMPLE,
        answer="ninety days [1]",
        abstained=False,
        citations=[],
        relevant_chunk_ids={"c1"},
        groundedness=None,
    )
    assert partial.fact_recall == 0.5 and not partial.correct and partial.missing_facts == ["12"]
    assert partial.citation_precision is None and not partial.cited_relevant

    gave_up = score_answer(
        EXAMPLE,
        answer="not found",
        abstained=True,
        citations=[],
        relevant_chunk_ids={"c1"},
        groundedness=None,
    )
    assert gave_up.fact_recall == 0.0 and not gave_up.abstention_correct


def test_unanswerable_questions_should_be_abstained_on():
    ok = score_answer(
        UNANSWERABLE,
        answer="not found",
        abstained=True,
        citations=[],
        relevant_chunk_ids=set(),
        groundedness=None,
    )
    bad = score_answer(
        UNANSWERABLE,
        answer="10M cover",
        abstained=False,
        citations=[],
        relevant_chunk_ids=set(),
        groundedness=0.0,
    )
    assert ok.abstention_correct and ok.fact_recall is None and ok.correct is None
    assert not bad.abstention_correct


@pytest.mark.parametrize(
    ("reply", "score"),
    [
        ('{"verdict": "correct", "reason": "Same period."}', 1.0),
        ('```json\n{"verdict": "partially_correct", "reason": "Misses cap."}\n```', 0.5),
        ('{"verdict": "incorrect", "reason": "Wrong number."}', 0.0),
        ('{"verdict": "maybe"}', None),
        ("I think it is correct.", None),
    ],
)
async def test_judge_verdicts_are_validated(reply, score):
    verdict = await judge_answer(FakeLLM(reply), question="q", reference="r", answer="a")
    assert verdict.score == score


# --- Aggregation, calibration, gate, reports -------------------------------------------------


def _result(id, *, answerable=True, correct=True, abstained=False, groundedness=1.0, recall5=1.0):
    return ExampleResult(
        id=id,
        question="?",
        answerable=answerable,
        tags=[],
        relevant_chunks=1,
        retrieved=[],
        retrieval={"recall@5": recall5, "mrr": recall5} if answerable else {},
        answer="a",
        citations=[],
        scores=AnswerScores(
            fact_recall=(1.0 if correct else 0.0) if answerable else None,
            correct=correct if answerable else None,
            abstained=abstained,
            abstention_correct=abstained != answerable,
            citation_precision=1.0,
            cited_relevant=True,
            groundedness=groundedness,
            missing_facts=[] if correct else ["x|y"],
        ),
        unsupported_claims=[],
        latency_ms=10.0,
        prompt_tokens=None,
        completion_tokens=None,
    )


RESULTS = [
    _result("a", correct=True, groundedness=1.0),
    _result("b", correct=True, groundedness=0.6),
    _result("c", correct=False, groundedness=0.2, recall5=0.0),
    _result("d", correct=False, abstained=True, groundedness=None),
    _result("u1", answerable=False, abstained=True, groundedness=None),
    _result("u2", answerable=False, abstained=False, groundedness=0.0),
]


def test_aggregate_metrics():
    m = aggregate(RESULTS)
    assert m["answer.accuracy"] == 0.5 and m["answer.false_abstention_rate"] == 0.25
    assert m["answer.abstention_accuracy"] == 0.5
    assert m["retrieval.recall@5"] == 0.75 and m["examples"] == 6
    assert m["grounding.mean"] == 0.6  # answered answerable only: (1.0 + 0.6 + 0.2) / 3


def test_calibration_shows_what_enforce_would_withhold():
    rows = {r["threshold"]: r for r in calibration(RESULTS)}
    assert rows[0.25] == {
        "threshold": 0.25,
        "withheld": 1,
        "withheld_correct": 0,
        "withheld_incorrect": 1,
        "shown_accuracy": 1.0,
    }
    assert rows[0.75]["withheld_correct"] == 1  # 0.6-grounded correct answer would be lost


def test_regression_gate():
    baseline = {"answer.accuracy": 0.9, "retrieval.mrr": 0.8, "answer.false_abstention_rate": 0.05}
    assert (
        compare_to_baseline(
            {"answer.accuracy": 0.86, "retrieval.mrr": 0.8, "answer.false_abstention_rate": 0.09},
            baseline,
        )
        == []
    )
    regressions = compare_to_baseline(
        {"answer.accuracy": 0.8, "retrieval.mrr": 0.9, "answer.false_abstention_rate": 0.2},
        baseline,
    )
    assert [r.metric for r in regressions] == ["answer.accuracy", "answer.false_abstention_rate"]
    assert compare_to_baseline({"judge.score": 0.1}, {"judge.score": 0.9}) == []  # not gated


def test_reports_are_written_and_readable_as_a_baseline(tmp_path):
    report = EvaluationReport(
        "sample-msa", 1, {"mode": "fast"}, aggregate(RESULTS), calibration(RESULTS), RESULTS, ["w1"]
    )
    json_path, md_path = write_reports(report, tmp_path)
    assert load_baseline(json_path)["answer.accuracy"] == 0.5
    text = render_markdown(report, [])
    assert "## Grounding calibration" in text and "✅ no regressions" in text
    assert "| c | missing x or y |" in text  # "|" alternatives don't break the table
    assert "answered an unanswerable question" in text and "* w1" in md_path.read_text()


def test_cli_exit_codes(monkeypatch, tmp_path):
    report = EvaluationReport("s", 1, {"mode": "fast"}, {"answer.accuracy": 0.5}, [], [])

    async def fake_run(args):
        return report

    monkeypatch.setattr(cli, "_run", fake_run)
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"metrics": {"answer.accuracy": 0.9}}))
    out = str(tmp_path / "out")
    assert cli.main(["run", "--out", out]) == 0
    assert cli.main(["run", "--out", out, "--baseline", str(baseline)]) == 1

    async def broken(args):
        raise RuntimeError("qdrant down")

    monkeypatch.setattr(cli, "_run", broken)
    assert cli.main(["run", "--out", out]) == 2


# --- A full evaluator run with fakes -----------------------------------------------------------


class KeywordRetriever:
    """In-memory keyword search over the sample contract's chunks."""

    def __init__(self, chunks):
        self.chunks = chunks

    async def retrieve(self, question, *, tenant_id, document_ids, version_ids, limit):
        terms = set(tokenize(question))
        scored = sorted(self.chunks, key=lambda c: -len(terms & set(tokenize(c.embedding_text))))
        return [_hit(c, 1.0 / (i + 1)) for i, c in enumerate(scored[:limit])]

    async def parents(self, *, tenant_id, parent_ids):
        return {}


def _hit(chunk, score):
    return RetrievedChunk(
        chunk_id=chunk.id,
        parent_id=None,
        document_id="d",
        document_title="MSA",
        version_id="v1",
        version_label="v1",
        text=chunk.text,
        heading_path=chunk.heading_path,
        section=chunk.section,
        section_title=chunk.section_title,
        clause=chunk.clause,
        clause_title=chunk.clause_title,
        page=chunk.page_start,
        page_end=chunk.page_end,
        chunk_type=chunk.chunk_type.value,
        score=score,
        clauses=chunk.clauses,
    )


class ReaderLLM:
    """Answers with the whole first evidence block, every sentence cited [1]
    (as the answer prompt requires)."""

    name, model = "fake", "reader"

    async def generate(self, messages, *, temperature=0.0, max_tokens=1024):
        block = re.search(r'cite="1">\n(.*?)\n</untrusted', messages[-1].content, re.S)
        if not block:
            return LLMResult(text="INSUFFICIENT_EVIDENCE", model=self.model)
        sentences = re.split(r"(?<=[.!?])\s+", " ".join(block.group(1).split()))
        return LLMResult(text=" ".join(f"{s} [1]" for s in sentences), model=self.model)

    async def aclose(self):
        return None


async def test_evaluator_runs_the_sample_dataset(sample_chunks):
    dataset = GoldenDataset.load(SAMPLE)
    evaluator = Evaluator(
        retriever=KeywordRetriever(sample_chunks),
        reranker=HeuristicReranker(),
        llm=ReaderLLM(),
        settings=Settings(),
        judge=FakeLLM(*['{"verdict": "correct"}'] * 30),
    )
    docs = {"msa": IngestedDocument("msa", "d", "v1", sample_chunks, 3)}
    report = await evaluator.run(dataset, tenant_id="t", documents=docs, config={"llm": "fake"})

    m = report.metrics
    assert report.warnings == [] and m["examples"] == 27
    assert m["retrieval.recall@10"] >= 0.8 and m["retrieval.mrr"] > 0.5
    # Quoting the right clause answers the question and is fully grounded.
    assert m["answer.accuracy"] >= 0.7 and m["grounding.mean"] >= 0.9
    assert m["judge.score"] == 1.0
    assert m["answer.abstention_accuracy"] == 0.0  # a reader that always answers never abstains
    by_id = {r.id: r for r in report.examples}
    assert by_id["renewal-notice"].relevant_chunks >= 1 and by_id["renewal-notice"].scores.correct
    assert report.config == {"mode": "fast", "llm": "fake"}


def test_evaluator_rejects_unknown_modes():
    with pytest.raises(ValueError):
        Evaluator(retriever=None, reranker=None, llm=None, settings=Settings(), mode="turbo")  # type: ignore[arg-type]
