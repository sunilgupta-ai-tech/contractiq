"""
Phase 10 tests: clause extraction, risk rules, comparison, key terms/dates,
the cached analyzer and summaries, and endpoint permissions.

Model and search are faked (tests.unit.test_rag.FakeLLM / FakeRetriever
style), so every rule and every validation step is tested deterministically.
"""

import json
import uuid
from dataclasses import replace

import pytest

from app.agents.clause_agent import ClauseAgent, ExtractedClause, parse_extraction
from app.agents.clause_topics import TOPICS, TOPICS_BY_KEY, coerce_attributes
from app.agents.comparison_agent import DiffKind, align
from app.agents.risk_agent import RiskAgent, Severity
from app.core.config import Settings
from app.core.security import SystemRole
from app.llm.base import LLMConfigError, LLMError
from app.rag.reranker import NoopReranker
from app.services.contract_service import ContractAnalyzer, VersionRef, key_dates, key_terms
from app.storage.local import LocalObjectStorage
from tests.tokens import token_for
from tests.unit.test_rag import FakeLLM, chunk

TENANT, DOC, VERSION = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
REF = VersionRef(TENANT, DOC, "Acme MSA", "MSA", VERSION, "v2")
INFO = REF.info


async def _no_sleep(_):
    return None


class ScopedRetriever:
    """Returns `chunks` for every topic query and records each call's scope."""

    def __init__(self, chunks):
        self.chunks = chunks
        self.calls = []

    async def retrieve(self, question, *, tenant_id, document_ids, version_ids, limit):
        self.calls.append((question, tenant_id, version_ids))
        return list(self.chunks)[:limit]

    async def parents(self, *, tenant_id, parent_ids):
        return {}


class TopicLLM(FakeLLM):
    """Replies per topic, keyed by the topic label found in the prompt."""

    def __init__(self, replies: dict[str, object], default: str = '{"found": false}'):
        super().__init__()
        self.by_label, self.default = replies, default

    async def generate(self, messages, *, temperature=0.0, max_tokens=1024):
        self.calls.append(messages)
        prompt = messages[-1].content
        for label, reply in self.by_label.items():
            if prompt.startswith(f"Topic: {label} "):
                if isinstance(reply, Exception):
                    raise reply
                return await self._ok(reply)
        if prompt.startswith("Contract:"):  # the summary prompt
            return await self._ok(self.by_label.get("summary", "{}"))
        return await self._ok(self.default)

    async def _ok(self, text):
        from app.llm.base import LLMResult

        return LLMResult(text=text, model=self.model)


NOTICE = chunk(
    1, clause="8.3", text="Either party may terminate on sixty (60) days' written notice."
)
CAP = chunk(2, clause="11.2", text="Liability shall not exceed the Fees paid in 12 months.")


def _clause(topic, *, found=True, error=False, source=NOTICE, **attributes):
    t = TOPICS_BY_KEY[topic]
    return ExtractedClause(
        topic=topic,
        label=t.label,
        found=found,
        error=error,
        verified=found,
        quote=source.text if found else None,
        attributes=coerce_attributes(t.attributes, attributes) if found else {},
        evidence=vars(replace(source)) if found else None,
    )


def _agent(chunks, llm, **settings):
    retriever = ScopedRetriever(chunks)
    agent = ClauseAgent(retriever, NoopReranker(), llm, Settings(**settings), sleep=_no_sleep)
    return agent, retriever


# --- Attribute coercion ---------------------------------------------------------------------


def test_attributes_are_coerced_to_their_declared_types():
    spec = {"days": "int", "on": "bool", "when": "date", "who": "str", "names": "list"}
    raw = {
        "days": "60 days",
        "on": "yes",
        "when": "2026-03-01T00:00",
        "who": "  A\nB ",
        "names": ["X", ""],
        "extra": 1,
    }
    assert coerce_attributes(spec, raw) == {
        "days": 60,
        "on": True,
        "when": "2026-03-01",
        "who": "A B",
        "names": ["X"],
    }
    bad = {"days": "sixty", "on": "maybe", "when": "2026-02-30", "who": "", "names": "X"}
    assert coerce_attributes(spec, bad) == dict.fromkeys(spec)
    assert coerce_attributes(spec, "not a dict") == dict.fromkeys(spec)
    assert coerce_attributes({"days": "int"}, {"days": True})["days"] is None
    assert coerce_attributes({"days": "int"}, {"days": -5})["days"] is None


# --- Clause extraction ----------------------------------------------------------------------


TERMINATION = TOPICS_BY_KEY["termination_convenience"]


def test_verified_quote_and_attributes():
    reply = json.dumps(
        {
            "found": True,
            "excerpt": 1,
            "quote": "Either party may terminate on sixty (60) days’ written  notice",
            "summary": "Either side can exit on 60 days' notice.",
            "attributes": {"permitted": True, "notice_days": "60", "party": "either"},
        }
    )
    clause = parse_extraction(TERMINATION, reply, [NOTICE])
    assert clause.found and clause.verified
    assert clause.attributes == {"permitted": True, "notice_days": 60, "party": "either"}
    assert (clause.clause, clause.page) == ("8.3", 1)
    assert clause.chunk.chunk_id == NOTICE.chunk_id


def test_paraphrased_quote_is_replaced_by_the_evidence():
    reply = json.dumps(
        {"found": True, "excerpt": 1, "quote": "Parties can quit with 2 months notice"}
    )
    clause = parse_extraction(TERMINATION, reply, [NOTICE])
    assert clause.found and not clause.verified and clause.quote == NOTICE.text


@pytest.mark.parametrize(
    "reply",
    [
        '{"found": true, "excerpt": 7, "quote": "x"}',  # invented excerpt
        '{"found": true, "excerpt": "first"}',  # not a number
        '{"found": false}',
        '{"found": "true", "excerpt": 1}',  # not a real boolean
    ],
)
def test_unsupported_answers_are_not_found(reply):
    clause = parse_extraction(TERMINATION, reply, [NOTICE])
    assert not clause.found and not clause.error and clause.evidence is None


def test_unparseable_reply_is_an_error_not_an_absence():
    clause = parse_extraction(TERMINATION, "Sure! The notice is 60 days.", [NOTICE])
    assert not clause.found and clause.error


async def test_agent_searches_only_the_version_and_skips_image_captions():
    caption = replace(chunk(3, text="[Image: chart] Credits"), chunk_type="image_caption")
    llm = TopicLLM(
        {
            "Termination for convenience": json.dumps(
                {
                    "found": True,
                    "excerpt": 1,
                    "quote": NOTICE.text,
                    "attributes": {"notice_days": 60},
                }
            )
        }
    )
    agent, retriever = _agent([caption, NOTICE], llm)
    clauses = await agent.extract(tenant_id=TENANT, version_id=VERSION)

    assert [c.topic for c in clauses] == [t.key for t in TOPICS]
    assert {(tenant, tuple(v)) for _, tenant, v in retriever.calls} == {(TENANT, (VERSION,))}
    found = {c.topic: c for c in clauses if c.found}
    assert set(found) == {"termination_convenience"}
    assert found["termination_convenience"].attributes["notice_days"] == 60
    # The caption was never shown to the model.
    assert all("[Image:" not in m.content for call in llm.calls for m in call)
    assert "<untrusted_document_" in llm.calls[0][-1].content


async def test_no_evidence_means_no_model_call():
    llm = TopicLLM({})
    agent, _ = _agent([], llm)
    clauses = await agent.extract(tenant_id=TENANT, version_id=VERSION)
    assert llm.calls == [] and not any(c.found or c.error for c in clauses)


async def test_temporary_failure_marks_one_topic_and_config_errors_stop():
    llm = TopicLLM({"Indemnity": LLMError("503")})
    agent, _ = _agent([NOTICE], llm)
    clauses = {c.topic: c for c in await agent.extract(tenant_id=TENANT, version_id=VERSION)}
    assert clauses["indemnity"].error and not clauses["assignment"].error

    agent, _ = _agent([NOTICE], TopicLLM({"Indemnity": LLMConfigError("bad key")}))
    with pytest.raises(LLMConfigError):
        await agent.extract(tenant_id=TENANT, version_id=VERSION)


# --- Risk rules --------------------------------------------------------------------------------


def _assess(*clauses, **settings):
    return RiskAgent(Settings(**settings)).assess(list(clauses), INFO)


def test_risky_facts_raise_cited_findings_most_severe_first():
    findings = _assess(
        _clause("liability_cap", source=CAP, capped=True, cap="12 months' fees"),
        _clause("indemnity", uncapped=True, indemnifying_party="Customer"),
        _clause(
            "auto_renewal", auto_renews=True, renewal_term_months=12, non_renewal_notice_days=90
        ),
        _clause("termination_convenience", permitted=True, notice_days=90),
        _clause("price_change", unilateral=True, has_ceiling=False),
        _clause("payment_terms", payment_days=90),
        _clause("confidentiality", duration_years=5),
    )
    rules = [f.rule for f in findings]
    assert rules == [
        "uncapped_indemnity",
        "automatic_renewal",
        "long_termination_notice",
        "unilateral_price_change",
        "long_payment_terms",
    ]
    assert [f.severity for f in findings][:2] == [Severity.HIGH, Severity.MEDIUM]
    indemnity = findings[0]
    assert indemnity.excerpt == NOTICE.text and indemnity.page == 1 and not indemnity.missing
    assert "Customer" in indemnity.rationale
    assert "90 days" in findings[1].rationale and "12-month" in findings[1].rationale


def test_missing_clauses_are_flagged_only_when_searched_without_error():
    findings = _assess(
        _clause("liability_cap", found=False),
        _clause("confidentiality", found=False, error=True),  # unknown: no flag
        _clause("termination_convenience", found=False),
    )
    by_rule = {f.rule: f for f in findings}
    assert set(by_rule) == {"no_liability_cap", "no_termination_for_convenience"}
    assert by_rule["no_liability_cap"].missing and by_rule["no_liability_cap"].excerpt is None
    assert _assess() == []  # topics never searched: nothing is claimed missing


def test_thresholds_and_home_jurisdiction_are_policy_settings():
    clauses = [
        _clause("termination_convenience", permitted=True, notice_days=90),
        _clause("governing_law", law="the laws of England and Wales"),
    ]
    assert {f.rule for f in _assess(*clauses)} == {"long_termination_notice"}
    assert _assess(*clauses, risk_max_notice_days=120, risk_home_jurisdiction="England") == []
    assert {
        f.rule for f in _assess(*clauses, risk_max_notice_days=120, risk_home_jurisdiction="India")
    } == {"foreign_governing_law"}


def test_finding_ids_are_stable_per_version_and_rule():
    first = _assess(_clause("auto_renewal", auto_renews=True))
    again = _assess(_clause("auto_renewal", auto_renews=True))
    other = RiskAgent(Settings()).assess(
        [_clause("auto_renewal", auto_renews=True)], replace(INFO, version_id="other")
    )
    assert first[0].id == again[0].id != other[0].id


# --- Comparison ----------------------------------------------------------------------------------


def test_alignment_by_topic_with_fact_notes_and_risk():
    v1_notice = replace(
        NOTICE, clause="8.3", text="Either party may terminate on thirty (30) days' notice."
    )
    v2_notice = replace(NOTICE, clause="9.2")  # renumbered in v2
    left = [
        _clause("termination_convenience", source=v1_notice, permitted=True, notice_days=30),
        _clause("governing_law", law="England and Wales"),
        _clause("confidentiality", duration_years=5),
    ]
    right = [
        _clause("termination_convenience", source=v2_notice, permitted=True, notice_days=90),
        _clause("governing_law", law="England and Wales"),
        _clause("indemnity", uncapped=True),
    ]
    findings = RiskAgent(Settings()).assess(right, INFO)
    rows = {r.topic: r for r in align(left, right, right_findings=findings)}

    notice = rows["termination_convenience"]
    assert notice.diff is DiffKind.CHANGED and notice.note == "Notice days: 30 → 90."
    assert (notice.left.clause, notice.right.clause) == ("8.3", "9.2")
    assert notice.risk is Severity.MEDIUM  # long notice introduced
    assert rows["governing_law"].diff is DiffKind.SAME and rows["governing_law"].risk is None
    assert rows["indemnity"].diff is DiffKind.MISSING and rows["indemnity"].left is None
    assert rows["indemnity"].risk is Severity.HIGH
    assert rows["confidentiality"].right is None
    assert "only in the left" in rows["confidentiality"].note
    assert list(rows) == [t.key for t in TOPICS if t.key in rows]  # topic order


def test_wording_only_change_reports_similarity():
    a = _clause("governing_law", law="England")
    b = _clause(
        "governing_law",
        source=replace(NOTICE, text="Governed by English law, exclusively."),
        law="England",
    )
    (row,) = align([a], [b])
    assert row.diff is DiffKind.CHANGED and row.note.startswith("Wording changed (")


# --- Key terms and dates --------------------------------------------------------------------------


def _analysis(clauses, fingerprint="fp"):
    from datetime import UTC, datetime

    from app.services.contract_service import ClauseAnalysis

    return ClauseAnalysis(fingerprint, "fake:m", datetime.now(UTC), clauses)


def test_key_dates_compute_the_non_renewal_deadline():
    analysis = _analysis(
        [
            _clause("term", effective_date="2025-01-01", expiry_date="2026-12-31"),
            _clause("auto_renewal", auto_renews=True, non_renewal_notice_days=90),
        ]
    )
    dates = [(str(d.date), d.kind, d.label) for d in key_dates(analysis, REF)]
    assert dates == [
        ("2025-01-01", "start", "Effective date"),
        ("2026-10-02", "notice", "Non-renewal notice deadline"),
        ("2026-12-31", "renewal", "Renews automatically"),
    ]
    no_renewal = _analysis([_clause("term", expiry_date="2026-12-31")])
    assert [d.kind for d in key_dates(no_renewal, REF)] == ["expiry"]


def test_key_terms_are_read_from_facts():
    terms = key_terms(
        _analysis(
            [
                _clause("termination_convenience", notice_days=60),
                _clause("parties", parties=["Acme Ltd", "Beta Inc"]),
                _clause("governing_law", found=False),
            ]
        )
    )
    assert [(t.label, t.value, t.clause) for t in terms] == [
        ("Parties", "Acme Ltd; Beta Inc", "8.3"),
        ("Termination notice", "60 days", "8.3"),
    ]


# --- Analyzer: caching and summary -------------------------------------------------------------------


def _analyzer(tmp_path, llm, chunks=(NOTICE, CAP), **kwargs):
    return ContractAnalyzer(
        storage=LocalObjectStorage(str(tmp_path)),
        settings=Settings(),
        retriever=ScopedRetriever(list(chunks)),
        reranker=NoopReranker(),
        llm=llm,
        embedding_model=kwargs.get("embedding_model", "fake:hash-embed:768"),
        sleep=_no_sleep,
    )


TERMINATION_REPLY = json.dumps(
    {"found": True, "excerpt": 1, "quote": NOTICE.text, "attributes": {"notice_days": 60}}
)


async def test_analysis_is_cached_per_version_and_fingerprint(tmp_path):
    llm = TopicLLM({"Termination for convenience": TERMINATION_REPLY})
    first = await _analyzer(tmp_path, llm).clauses(REF)
    calls = len(llm.calls)
    assert not first.cached and calls == len(TOPICS)

    again = await _analyzer(tmp_path, llm).clauses(REF)
    assert again.cached and len(llm.calls) == calls
    assert [c.to_dict() for c in again.clauses] == [c.to_dict() for c in first.clauses]

    # Another embedding model (or model/extractor version) is a different fingerprint.
    await _analyzer(tmp_path, llm, embedding_model="other:m:768").clauses(REF)
    assert len(llm.calls) == 2 * calls
    await _analyzer(tmp_path, llm).clauses(REF, refresh=True)
    assert len(llm.calls) == 3 * calls


async def test_failed_topics_are_kept_and_only_they_are_retried(tmp_path):
    # Found in local testing with Gemini: re-running all 15 topics whenever
    # one failed multiplied cost on every risk/summary request.
    llm = TopicLLM({"Indemnity": LLMError("503")})
    first = await _analyzer(tmp_path, llm).clauses(REF)
    assert not first.complete and first.cached is False
    stored = await _analyzer(tmp_path, llm).cached(REF)
    assert stored is not None and [c.topic for c in stored.clauses if c.error] == ["indemnity"]

    llm.by_label = {"Termination for convenience": TERMINATION_REPLY}  # indemnity now works
    calls = len(llm.calls)
    second = await _analyzer(tmp_path, llm).clauses(REF)
    assert len(llm.calls) == calls + 1  # just the failed topic
    assert second.complete
    assert await _analyzer(tmp_path, llm).cached(REF) is not None


def test_excerpt_number_given_as_text_is_accepted():
    reply = json.dumps({"found": True, "excerpt": "1", "quote": NOTICE.text})
    clause = parse_extraction(TERMINATION, reply, [NOTICE])
    assert clause.found and clause.verified


async def test_summary_cites_clauses_and_validates_obligations(tmp_path):
    summary_reply = json.dumps(
        {
            "overview": "Either party may terminate on 60 days' notice [1]. Liability is capped [2][9].",
            "obligations": [
                {"party": "Customer", "obligation": "Give 60 days' notice.", "cite": 1},
                {"party": "Supplier", "obligation": "Invented.", "cite": 9},
                "not an object",
            ],
        }
    )
    llm = TopicLLM(
        {
            "Termination for convenience": TERMINATION_REPLY,
            "Limitation of liability": json.dumps(
                {"found": True, "excerpt": 2, "quote": CAP.text, "attributes": {"capped": True}}
            ),
            "summary": summary_reply,
        }
    )
    summary = await _analyzer(tmp_path, llm).summary(REF)

    assert summary.overview.endswith("Liability is capped [2].")  # [9] removed
    assert [c.clause for c in summary.citations] == ["8.3", "11.2"]
    assert [(o.party, o.clause) for o in summary.obligations] == [("Customer", "8.3")]
    assert [t.label for t in summary.key_terms] == ["Termination notice"]
    assert summary.risk_counts.high == 0 and summary.disclaimer

    calls = len(llm.calls)
    cached = await _analyzer(tmp_path, llm).summary(REF)
    assert len(llm.calls) == calls and cached.overview == summary.overview


async def test_nothing_found_means_no_summary_call(tmp_path):
    llm = TopicLLM({})
    summary = await _analyzer(tmp_path, llm, chunks=()).summary(REF)
    assert llm.calls == [] and summary.citations == [] and "No standard clauses" in summary.overview


# --- Endpoints ---------------------------------------------------------------------------------------


ENDPOINTS = [
    ("/api/v1/contracts/summarize", {"document_id": DOC}),
    ("/api/v1/contracts/extract-clauses", {"document_id": DOC}),
    ("/api/v1/contracts/compare", {"left_version_id": VERSION, "right_version_id": DOC}),
    ("/api/v1/contracts/risk-analysis", {}),
    ("/api/v1/contracts/portfolio-summary", {}),
]


@pytest.mark.parametrize(("path", "body"), ENDPOINTS)
async def test_analysis_needs_a_token_and_the_analysis_permission(client, settings, path, body):
    assert (await client.post(path, json=body)).status_code == 401
    token = token_for(settings, SystemRole.VIEWER, tenant_id=TENANT)
    response = await client.post(path, json=body, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


# --- Multi-document requests: inline budget, then the worker queue ------------------------------


class FakeQueue:
    def __init__(self, fail=False):
        self.jobs, self.fail = [], fail

    async def enqueue_job(self, name, *args, _job_id=None):
        if self.fail:
            raise ConnectionError("redis down")
        self.jobs.append((name, args, _job_id))


async def test_beyond_the_inline_budget_documents_are_queued(tmp_path):
    from types import SimpleNamespace

    from app.services.contract_service import ContractService

    llm = TopicLLM({"Termination for convenience": TERMINATION_REPLY})
    analyzer = _analyzer(tmp_path, llm)
    queue = FakeQueue()
    resources = SimpleNamespace(settings=Settings(analysis_sync_documents=1), queue=queue)
    service = ContractService(
        None,
        uuid.UUID(TENANT),
        resources,
        analyzer_factory=lambda _: analyzer,  # type: ignore[arg-type]
    )
    second = replace(REF, document_id=str(uuid.uuid4()), version_id=str(uuid.uuid4()))

    ready, pending = await service.analyses([REF, second])
    assert [ref for ref, _ in ready] == [REF] and pending == [second.document_id]
    ((name, args, job_id),) = queue.jobs
    assert name == "analyze_version" and args == (TENANT, second.document_id, second.version_id)
    assert job_id.startswith(f"analyze:{second.version_id}:")

    # A cached analysis doesn't use the budget; a queue outage still reports pending.
    service.resources = SimpleNamespace(
        settings=Settings(analysis_sync_documents=0), queue=FakeQueue(fail=True)
    )
    ready, pending = await service.analyses([REF, second])
    assert [ref for ref, _ in ready] == [REF] and pending == [second.document_id]
