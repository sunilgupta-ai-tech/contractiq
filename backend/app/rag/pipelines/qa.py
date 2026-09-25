"""
The contract Q&A pipeline (retrieval-augmented generation).

    question
      1. retrieve   hybrid search (dense + keyword, RRF), tenant-filtered
      2. rerank     structural/lexical signals, keep top N
      3. context    expand hits to their sections within a token budget
      4. generate   LLM answers ONLY from the numbered evidence, citing [n]
      5. cite       verify + renumber citations, resolve to page/clause

Each step is timed and reported (`steps`), which the UI shows as the
"how this answer was built" trail and which helps spot slow stages.

Design choices
--------------
* No evidence -> no LLM call. If search finds nothing, the pipeline answers
  "not found" itself: cheaper, faster, and the model can't be tempted to
  answer from general knowledge.
* The model signals "can't answer from these excerpts" with an exact
  sentinel (prompts.INSUFFICIENT_EVIDENCE), turned into the same friendly
  message, so "not found" is detected reliably rather than by guessing
  from free text.
* One retry for temporary LLM errors. Configuration errors (bad key) and
  blocked responses are not retried.
* The pipeline has no database access; persistence is QueryService's job.
  That keeps it testable with in-memory fakes and reusable by the Phase 8
  agent as a tool.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field

from app.core.config import Settings
from app.core.logging import get_logger
from app.guardrails.prompt_injection import scan_for_injection
from app.llm.base import LLMBlockedError, LLMConfigError, LLMError, LLMProvider, LLMResult
from app.rag.context import build_evidence
from app.rag.prompts.system import INSUFFICIENT_EVIDENCE, PROMPT_VERSION, build_messages
from app.rag.reranker import Reranker
from app.rag.retriever import Retriever
from app.rag.types import Citation, EvidenceBlock
from app.services.citation_service import resolve_citations

logger = get_logger(__name__)

NOT_FOUND_MESSAGE = (
    "I couldn't find this in the selected contracts. Try rephrasing the question, "
    "or check that the right documents are selected and have finished processing."
)
BLOCKED_MESSAGE = "An answer could not be generated for this question. Please rephrase it."


@dataclass
class Step:
    key: str
    label: str
    detail: str
    duration_ms: float
    status: str = "done"


@dataclass
class RagAnswer:
    answer: str
    citations: list[Citation]
    insufficient_evidence: bool
    cited_fraction: float
    steps: list[Step]
    model: str | None
    prompt_version: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    # Suspicious instruction-like text seen in the question or evidence.
    # Logged and returned for review; never blocks (see guardrails).
    injection_flags: list[str] = field(default_factory=list)


class QAPipeline:
    def __init__(
        self,
        retriever: Retriever,
        reranker: Reranker,
        llm: LLMProvider,
        settings: Settings,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.retriever = retriever
        self.reranker = reranker
        self.llm = llm
        self.settings = settings
        self._sleep = sleep

    async def answer(
        self,
        question: str,
        *,
        tenant_id: str,
        document_ids: Sequence[str] | None = None,
        version_ids: Sequence[str] | None = None,
        history: list[tuple[str, str]] | None = None,
    ) -> RagAnswer:
        steps: list[Step] = []
        flags = [f"question:{r}" for r in scan_for_injection(question).matched_rules]

        # 1. retrieve
        started = time.perf_counter()
        candidates = await self.retriever.retrieve(
            question,
            tenant_id=tenant_id,
            document_ids=document_ids,
            version_ids=version_ids,
            limit=self.settings.retrieval_candidates,
        )
        steps.append(_step("retrieve", "Hybrid search", f"{len(candidates)} candidates", started))
        if not candidates:
            return self._not_found(steps, flags)

        # 2. rerank
        started = time.perf_counter()
        top = await self.reranker.rerank(question, candidates, self.settings.rerank_top_n)
        steps.append(_step("rerank", "Rerank", f"top {len(top)} ({self.reranker.name})", started))

        # 3. context (small-to-big)
        started = time.perf_counter()
        parents = await self.retriever.parents(
            tenant_id=tenant_id, parent_ids=[c.parent_id for c in top if c.parent_id]
        )
        blocks = build_evidence(top, parents, max_tokens=self.settings.context_max_tokens)
        flags += _evidence_flags(blocks)
        steps.append(_step("context", "Build context", f"{len(blocks)} evidence blocks", started))

        # 4. generate
        started = time.perf_counter()
        try:
            result = await self._generate(question, blocks, history)
        except LLMBlockedError:
            logger.warning("llm_blocked")
            steps.append(_step("generate", "Generate answer", "blocked", started, "retry"))
            return RagAnswer(
                answer=BLOCKED_MESSAGE,
                citations=[],
                insufficient_evidence=True,
                cited_fraction=0.0,
                steps=steps,
                model=self.llm.model,
                prompt_version=PROMPT_VERSION,
                injection_flags=flags,
            )
        steps.append(_step("generate", "Generate answer", result.model, started))

        # 5. cite
        started = time.perf_counter()
        if result.text.strip().strip(".").upper() == INSUFFICIENT_EVIDENCE:
            answer = self._not_found(steps, flags)
            answer.model = result.model
            answer.prompt_tokens, answer.completion_tokens = (
                result.prompt_tokens,
                result.completion_tokens,
            )
            return answer
        cited = resolve_citations(result.text, blocks)
        steps.append(
            _step("cite", "Verify citations", f"{len(cited.citations)} citations", started)
        )
        if flags:
            logger.warning("prompt_injection_suspected", extra={"rules": flags})
        return RagAnswer(
            answer=cited.text,
            citations=cited.citations,
            insufficient_evidence=False,
            cited_fraction=cited.cited_fraction,
            steps=steps,
            model=result.model,
            prompt_version=PROMPT_VERSION,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            injection_flags=flags,
        )

    async def _generate(
        self,
        question: str,
        blocks: list[EvidenceBlock],
        history: list[tuple[str, str]] | None,
    ) -> LLMResult:
        messages = build_messages(question, blocks, history)
        for attempt in range(2):  # one retry for temporary errors
            try:
                return await self.llm.generate(
                    messages,
                    temperature=0.0,  # deterministic, extractive answers
                    max_tokens=self.settings.llm_max_output_tokens,
                )
            except (LLMConfigError, LLMBlockedError):
                raise
            except LLMError:
                if attempt == 1:
                    raise
                logger.warning("llm_retry")
                await self._sleep(1.0)
        raise AssertionError("unreachable")

    def _not_found(self, steps: list[Step], flags: list[str]) -> RagAnswer:
        return RagAnswer(
            answer=NOT_FOUND_MESSAGE,
            citations=[],
            insufficient_evidence=True,
            cited_fraction=0.0,
            steps=steps,
            model=None,
            prompt_version=PROMPT_VERSION,
            injection_flags=flags,
        )


def _step(key: str, label: str, detail: str, started: float, status: str = "done") -> Step:
    return Step(key, label, detail, round((time.perf_counter() - started) * 1000, 1), status)


def _evidence_flags(blocks: list[EvidenceBlock]) -> list[str]:
    flags = []
    for block in blocks:
        for rule in scan_for_injection(block.text).matched_rules:
            flags.append(f"evidence[{block.number}]:{rule}")
    return flags
