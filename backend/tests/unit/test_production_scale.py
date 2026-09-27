"""Phase 21: production-scale building blocks — resilient model calls,
answer cache, streamed uploads, parser fallbacks and review flags."""

import hashlib
import io

import pytest
from fastapi import UploadFile

from app.agents.results import AgentAnswer
from app.core.exceptions import FileTooLargeError
from app.document_processing.parser import CorruptPdfError
from app.guardrails.evidence_validator import ClaimCheck, GroundingReport
from app.llm.base import ChatMessage, LLMBlockedError, LLMConfigError, LLMError, LLMResult
from app.llm.resilient import CircuitBreaker, CircuitOpenError, ResilientLLM
from app.rag.pipelines.qa import RagAnswer, Step
from app.services import answer_cache, pdf_service
from app.services.document_service import spool_upload
from app.services.pdf_service import PdfOptions, parse_pdf
from tests import pdf_factory

MESSAGES = [ChatMessage("user", "q")]


class ScriptedLLM:
    """Fails with the given errors in order, then answers."""

    def __init__(self, *errors: Exception, model: str = "primary") -> None:
        self.errors = list(errors)
        self.name, self.model = "fake", model
        self.calls = 0

    async def generate(self, messages, *, temperature=0.0, max_tokens=1024) -> LLMResult:
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return LLMResult(text=f"answer from {self.model}", model=self.model)

    async def aclose(self) -> None:
        return None


async def _no_sleep(_: float) -> None:
    return None


# --- Resilient model calls ------------------------------------------------------------


async def test_temporary_errors_are_retried():
    primary = ScriptedLLM(LLMError("429"), LLMError("503"))
    llm = ResilientLLM(primary, max_retries=2, sleep=_no_sleep)
    assert (await llm.generate(MESSAGES)).text == "answer from primary"
    assert primary.calls == 3


async def test_after_retries_the_fallback_model_answers():
    primary = ScriptedLLM(LLMError("429"), LLMError("429"), LLMError("429"))
    fallback = ScriptedLLM(model="lite")
    llm = ResilientLLM(primary, fallback=fallback, max_retries=2, sleep=_no_sleep)
    assert (await llm.generate(MESSAGES)).text == "answer from lite"


@pytest.mark.parametrize("error", [LLMConfigError("bad key"), LLMBlockedError("safety")])
async def test_errors_retrying_cannot_fix_are_not_retried(error):
    primary = ScriptedLLM(error)
    llm = ResilientLLM(primary, fallback=ScriptedLLM(model="lite"), sleep=_no_sleep)
    with pytest.raises(type(error)):
        await llm.generate(MESSAGES)
    assert primary.calls == 1


async def test_the_circuit_opens_then_recovers_after_the_cooldown():
    now = [0.0]
    breaker = CircuitBreaker(threshold=2, cooldown_s=30, clock=lambda: now[0])
    primary = ScriptedLLM(LLMError("500"), LLMError("500"))
    llm = ResilientLLM(primary, max_retries=5, breaker=breaker, sleep=_no_sleep)
    with pytest.raises(LLMError):
        await llm.generate(MESSAGES)
    assert breaker.is_open and primary.calls == 2
    # While open, the primary is not called at all.
    with pytest.raises(CircuitOpenError):
        await llm.generate(MESSAGES)
    assert primary.calls == 2
    now[0] = 31.0  # cooldown over: one trial call, which succeeds
    assert (await llm.generate(MESSAGES)).text == "answer from primary"
    assert not breaker.is_open


# --- Answer cache ---------------------------------------------------------------------


def _answer(**extra) -> RagAnswer:
    base = dict(
        answer="Notice is 60 days [1].",
        citations=[],
        insufficient_evidence=False,
        cited_fraction=1.0,
        steps=[Step(key="answer", label="Answer", detail="", duration_ms=5.0)],
        model="gemini-2.5-flash",
        prompt_version="qa-v4",
        prompt_tokens=900,
        completion_tokens=40,
        grounding=GroundingReport(score=1.0, claims=[ClaimCheck("Notice is 60 days", [1], True)]),
    )
    return (
        AgentAnswer(**base, intent="qa", queries=["notice"])
        if extra.get("agent")
        else RagAnswer(**base)
    )


def test_cached_answers_round_trip_and_cost_nothing():
    for original in (_answer(), _answer(agent=True)):
        restored = answer_cache.from_json(answer_cache.to_json(original))
        assert type(restored) is type(original)
        assert restored.answer == original.answer and restored.grounding.score == 1.0
        assert (restored.prompt_tokens, restored.completion_tokens) == (0, 0)
    assert answer_cache.from_json(answer_cache.to_json(_answer(agent=True))).queries == ["notice"]


def test_cache_keys_separate_tenants_access_and_corpus_changes():
    base = dict(
        question="What is the notice period?",
        mode="agent",
        document_ids=[],
        version_ids=[],
        hidden_document_ids=[],
        corpus_version="3:2026-09-28T10:00:00",
        prompt_version="qa-v4",
        model="m",
    )
    key = answer_cache.cache_key("t1", **base)
    assert key.startswith("ciq:t1:answer:")
    assert (
        answer_cache.cache_key("t1", **{**base, "question": "  what is the NOTICE period? "}) == key
    )
    for change in (
        {"hidden_document_ids": ["d-secret"]},
        {"corpus_version": "4:2026-09-28T11:00:00"},
        {"document_ids": ["d-1"]},
        {"model": "other"},
    ):
        assert answer_cache.cache_key("t1", **{**base, **change}) != key
    assert answer_cache.cache_key("t2", **base) != key


# --- Streamed uploads -----------------------------------------------------------------


async def test_uploads_stream_to_disk_with_their_hash():
    data = b"%PDF-1.7\n" + b"x" * 3_000_000
    spooled = await spool_upload(
        UploadFile(io.BytesIO(data), filename="big.pdf"), max_bytes=10_000_000
    )
    try:
        assert spooled.size == len(data)
        assert spooled.sha256 == hashlib.sha256(data).hexdigest()
        assert spooled.path.read_bytes() == data
    finally:
        spooled.discard()
    assert not spooled.path.exists()


async def test_oversized_uploads_stop_early_and_leave_nothing_behind(tmp_path, monkeypatch):
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    with pytest.raises(FileTooLargeError):
        await spool_upload(UploadFile(io.BytesIO(b"x" * 5000), filename="big.pdf"), max_bytes=2048)
    assert list(tmp_path.iterdir()) == []


# --- Parser fallbacks -----------------------------------------------------------------


def test_an_unreadable_page_is_ocrd_instead_of_failing_the_document(monkeypatch):
    real = pdf_service.extract_page

    def flaky(page, number):
        if number == 2:
            raise RuntimeError("broken content stream")
        return real(page, number)

    monkeypatch.setattr(pdf_service, "extract_page", flaky)
    result = parse_pdf(pdf_factory.contract_pdf(), PdfOptions())
    assert result.document.page_count == 3
    assert result.document.pages[1].is_scanned  # handed to OCR
    assert any("Page 2" in w for w in result.warnings)


def test_a_pdf_mupdf_rejects_is_recovered_by_the_fallback_reader(monkeypatch):
    def reject(data):
        raise CorruptPdfError()

    monkeypatch.setattr(pdf_service, "open_pdf", reject)
    result = parse_pdf(pdf_factory.contract_pdf(), PdfOptions())
    assert result.document.metadata["parser"] == "pdfplumber-fallback"
    text = " ".join(p.text for p in result.document.pages)
    assert "MASTER SERVICES AGREEMENT" in text and "thirty days of written notice" in text
    assert result.warnings


def test_garbage_still_fails_as_corrupt():
    with pytest.raises(CorruptPdfError):
        parse_pdf(b"%PDF-1.7 not really", PdfOptions())
