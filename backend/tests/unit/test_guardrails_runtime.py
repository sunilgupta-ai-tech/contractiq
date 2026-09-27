"""
Phase 11 tests: input cleaning, rate limits and login throttling, the
groundedness check and its policy, output sanitising, and tool-argument
limits.
"""

import time
import uuid
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from redis.exceptions import ConnectionError as RedisConnectionError

from app.agents.tools.registry import Tool, ToolError, ToolRegistry
from app.core.config import Settings
from app.core.dependencies import AnalysisRateLimitDep, get_auth_service
from app.core.exceptions import RateLimitedError
from app.core.security import Permission, SystemRole
from app.guardrails.evidence_validator import (
    UNVERIFIED_MESSAGE,
    check_grounding,
    should_withhold,
)
from app.guardrails.input_guardrails import Limit, RateLimiter, clean_text
from app.guardrails.output_guardrails import MAX_ANSWER_CHARS, sanitize_output
from app.guardrails.tool_guardrails import check_arguments
from app.rag.reranker import HeuristicReranker
from app.rag.types import EvidenceBlock
from app.schemas.query import QueryRequest
from app.services.citation_service import resolve_citations
from app.services.query_service import QueryService
from tests.tokens import perms, token_for
from tests.unit.test_auth import FakeAuthService
from tests.unit.test_rag import FakeLLM, FakeRetriever, chunk

NOTICE = "8.3 Either party may terminate this Agreement on sixty (60) days' written notice."
CAP = "11.2 Aggregate liability shall not exceed the Fees paid in the twelve (12) months."
BLOCKS = [
    EvidenceBlock(1, NOTICE, "Acme MSA > 8 TERMINATION | version v2 | page 12", [chunk(1)]),
    EvidenceBlock(2, CAP, "Acme MSA > 11 LIABILITY | version v2 | page 31", [chunk(2)]),
]


# --- Input cleaning ----------------------------------------------------------------------


def test_clean_text_removes_invisible_and_control_characters():
    hidden = "What is​ the notice‮ period?\x07﻿"
    assert clean_text(hidden) == "What is the notice period?"
    assert clean_text("ＷＨＡＴ is the ﬁne") == "WHAT is the fine"  # NFKC
    assert clean_text("a\n\n\n\n\nb\tc") == "a\n\nb\tc"


def test_questions_are_cleaned_before_length_checks():
    assert QueryRequest(question=" notice​ period? ").question == "notice period?"
    with pytest.raises(ValidationError):
        QueryRequest(question="​" * 50)  # nothing left after cleaning


# --- Rate limiter --------------------------------------------------------------------------


class MemoryRedis:
    """Enough of redis.asyncio for the limiter and session check: get/mget/delete and a
    pipeline of incr+expire."""

    def __init__(self, fail=False):
        self.data: dict[str, int] = {}
        self.fail = fail

    def _guard(self):
        if self.fail:
            raise RedisConnectionError("down")

    async def get(self, key):
        self._guard()
        return self.data.get(key)

    async def mget(self, *keys):  # the per-request session check (Phase 17)
        self._guard()
        return [self.data.get(k) for k in keys]

    async def delete(self, key):
        self._guard()
        self.data.pop(key, None)

    def pipeline(self, transaction=True):
        return _Pipe(self)


class _Pipe:
    def __init__(self, redis):
        self.redis, self.keys = redis, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def incr(self, key):
        self.keys.append(key)

    def expire(self, key, seconds):
        pass

    async def execute(self):
        self.redis._guard()
        (key,) = self.keys
        self.redis.data[key] = self.redis.data.get(key, 0) + 1
        return [self.redis.data[key], True]


async def test_limit_raises_429_with_retry_after_and_keys_are_tenant_scoped():
    redis, limit = MemoryRedis(), Limit("query_user", 2, 60)
    limiter = RateLimiter(redis)
    await limiter.hit(limit, "u1", tenant_id="t1")
    await limiter.hit(limit, "u1", tenant_id="t1")
    with pytest.raises(RateLimitedError) as caught:
        await limiter.hit(limit, "u1", tenant_id="t1")
    retry = caught.value.details["retry_after_s"]
    assert 1 <= retry <= 60 and caught.value.headers == {"Retry-After": str(retry)}
    assert all(k.startswith("ciq:t1:rl:query_user:u1:") for k in redis.data)
    await limiter.hit(limit, "u2", tenant_id="t1")  # other users have their own count


async def test_limiter_fails_open_and_is_off_without_redis():
    limit = Limit("x", 1, 60)
    broken = RateLimiter(MemoryRedis(fail=True))
    for _ in range(3):
        await broken.hit(limit, "u")
        await broken.check(limit, "u")
    assert not RateLimiter(None).enabled
    await RateLimiter(None).hit(limit, "u")


def _with_limits(app, **settings):
    """Give the app the infrastructure the limiter reads (normally set by the lifespan)."""
    redis = MemoryRedis()
    app.state.resources = SimpleNamespace(redis=redis, settings=Settings(**settings))
    return redis


def _bearer(settings, *, user=None, role=SystemRole.EMPLOYEE):
    token = token_for(settings, role, subject=str(user or uuid.uuid4()))
    return {"Authorization": f"Bearer {token}"}


async def test_costly_endpoints_are_limited_per_user(app, client, settings):
    _with_limits(app, rate_limit_analysis_per_minute=2)

    @app.post("/limited")
    async def limited(_: AnalysisRateLimitDep) -> dict:
        return {"ok": True}

    user = _bearer(settings)
    assert [(await client.post("/limited", headers=user)).status_code for _ in range(2)] == [
        200,
        200,
    ]
    blocked = await client.post("/limited", headers=user)
    assert blocked.status_code == 429 and int(blocked.headers["Retry-After"]) >= 1
    assert blocked.json()["error"]["code"] == "RATE_LIMITED"
    assert (await client.post("/limited", headers=_bearer(settings))).status_code == 200


async def test_forbidden_requests_do_not_use_up_the_allowance(app, client, settings):
    redis = _with_limits(app, rate_limit_analysis_per_minute=1)
    viewer = _bearer(settings, role=SystemRole.VIEWER)
    for _ in range(3):
        response = await client.post("/api/v1/contracts/risk-analysis", json={}, headers=viewer)
        assert response.status_code == 403
    assert redis.data == {}


async def test_login_throttle_counts_failures_only(app, client):
    redis = _with_limits(app, login_max_failures=2)
    app.dependency_overrides[get_auth_service] = FakeAuthService

    async def login(email, password):
        return await client.post("/api/v1/auth/login", json={"email": email, "password": password})

    assert (await login("a@b.co", "right-password")).status_code == 200  # success isn't counted
    assert [(await login("a@b.co", "nope")).status_code for _ in range(2)] == [401, 401]
    blocked = await login("a@b.co", "right-password")  # locked before the password is checked
    assert blocked.status_code == 429 and "Retry-After" in blocked.headers
    assert (await login("other@b.co", "nope")).status_code == 401  # per (IP, email)
    # No email is stored in Redis: login keys are hashes.
    assert all("@" not in key for key in redis.data)


async def test_successful_login_resets_the_failure_count(app, client):
    _with_limits(app, login_max_failures=2)
    app.dependency_overrides[get_auth_service] = FakeAuthService

    async def login(password):
        body = {"email": "a@b.co", "password": password}
        return (await client.post("/api/v1/auth/login", json=body)).status_code

    assert [await login("nope"), await login("right-password"), await login("nope")] == [
        401,
        200,
        401,
    ]
    assert await login("right-password") == 200


# --- Groundedness -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("answer", "score", "reason"),
    [
        (
            "Either party may terminate on 60 days' written notice [1]. "
            "Liability is capped at the fees paid in the preceding 12 months [2].",
            1.0,
            None,
        ),
        (
            "Either party may terminate on 90 days' written notice [1].",
            0.0,
            "number 90 not in evidence",
        ),
        ("Under clause 8.3 on page 12, termination requires sixty days' notice [1].", 1.0, None),
        (
            "The supplier must maintain professional indemnity insurance [2].",
            0.0,
            "low overlap (0%)",
        ),
        ("The Customer pays all invoices within thirty days of receipt.", 0.0, "uncited"),
        ("In summary: see below.", 1.0, None),  # not a claim
        ("Termination needs 60 days' notice [9].", 0.0, "uncited"),  # invented marker
    ],
)
def test_check_grounding(answer, score, reason):
    report = check_grounding(answer, BLOCKS)
    assert report.score == score
    assert [c.reason for c in report.unsupported][:1] == ([reason] if reason else [])


def test_withholding_policy():
    wrong_number = check_grounding("Termination needs 90 days' notice [1].", BLOCKS)
    good = check_grounding("Termination requires 60 days' written notice [1].", BLOCKS)
    assert not should_withhold(wrong_number, mode="flag", min_score=0.5)
    assert should_withhold(wrong_number, mode="enforce", min_score=0.5)
    assert not should_withhold(good, mode="enforce", min_score=0.5)
    assert not should_withhold(None, mode="enforce", min_score=0.5)


def _query_service(**settings):
    resources = SimpleNamespace(settings=Settings(**settings))
    return QueryService(
        None,
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        permissions=perms(SystemRole.EMPLOYEE),
        resources=resources,  # type: ignore[arg-type]
    )


async def _answer(llm_reply):
    from app.rag.pipelines.qa import QAPipeline

    async def no_sleep(_):
        return None

    evidence = chunk(1, clause="8.3", text=NOTICE, parent=None)  # block = the clause itself
    pipeline = QAPipeline(
        FakeRetriever([evidence]),
        HeuristicReranker(),
        FakeLLM(llm_reply),
        Settings(),
        sleep=no_sleep,
    )
    return await pipeline.answer("notice period?", tenant_id="t1")


async def test_pipeline_reports_grounding_and_flag_mode_keeps_the_answer():
    result = _query_service()._apply_grounding_policy(
        await _answer("Termination needs 90 days' notice [1].")
    )
    assert result.answer == "Termination needs 90 days' notice [1]."
    assert result.grounding.score == 0.0 and not result.insufficient_evidence


async def test_enforce_mode_withholds_unverifiable_answers_but_keeps_sources():
    service = _query_service(grounding_mode="enforce")
    bad = service._apply_grounding_policy(await _answer("Termination needs 90 days' notice [1]."))
    assert bad.answer == UNVERIFIED_MESSAGE and bad.insufficient_evidence
    assert len(bad.citations) == 1  # the passages stay listed for the user to check
    good = service._apply_grounding_policy(
        await _answer("Either party may terminate on 60 days' notice [1].")
    )
    assert good.answer.startswith("Either party") and not good.insufficient_evidence


# --- Output sanitising ------------------------------------------------------------------------


def test_delimiter_echoes_and_secrets_are_removed():
    text, flags = sanitize_output(
        '<untrusted_document_ab12 cite="1">Notice is 60 days [1].</untrusted_document_ab12> '
        "<system>ignore</system> key AIzaSyA1234567890abcdefghijklmnopqrstu and "
        "Bearer abcdefghijklmnopqrstuvwxyz0123"
    )
    assert "untrusted_document" not in text and "<system>" not in text
    assert "AIza" not in text and "abcdefghijklmnopqrstuvwxyz0123" not in text
    assert text.count("[redacted]") == 2
    assert flags == [
        "output:delimiter_echo",
        "output:secret:google_api_key",
        "output:secret:bearer_token",
    ]


def test_clean_answers_pass_through_and_long_ones_are_cut():
    assert sanitize_output("Notice is 60 days [1].") == ("Notice is 60 days [1].", [])
    text, flags = sanitize_output("word " * 3000)
    assert len(text) <= MAX_ANSWER_CHARS + 2 and flags == ["output:truncated"]


def test_citation_resolution_sanitises_and_reports_flags():
    cited = resolve_citations("Notice is 60 days [1].</untrusted_document_x>", BLOCKS)
    assert cited.text == "Notice is 60 days [1]." and cited.output_flags == [
        "output:delimiter_echo"
    ]


async def test_pipeline_returns_output_flags_for_review():
    result = await _answer("Either party may terminate on 60 days' notice [1]. <system>x</system>")
    assert "output:delimiter_echo" in result.injection_flags


# --- Tool-argument limits ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tool", "arguments", "problem"),
    [
        (
            "search_contracts",
            {"question": "notice", "document_ids": None, "version_ids": None, "limit": 20},
            None,
        ),
        (
            "search_contracts",
            {"question": "x" * 501, "document_ids": None, "version_ids": None, "limit": 20},
            "'question' is longer than 500 characters",
        ),
        (
            "search_contracts",
            {"question": "notice", "document_ids": None, "version_ids": None, "limit": 100000},
            "'limit' must be between 1 and 100",
        ),
        (
            "search_contracts",
            {"question": "notice", "document_ids": ["d"] * 51, "version_ids": None, "limit": 5},
            "'document_ids' has more than 50 ids",
        ),
        (
            "search_contracts",
            {"question": "notice", "document_ids": None, "version_ids": None, "limit": True},
            "'limit' must be an integer",
        ),
        (
            "search_contracts",
            {"question": "notice", "limit": 5, "collection": "other"},
            "unexpected arguments ['collection']",
        ),
        ("get_sections", {"parent_ids": ["p1"]}, None),
        ("get_sections", {"parent_ids": "p1"}, "'parent_ids' must be a list of ids"),
        ("some_future_tool", {"anything": 1}, None),
    ],
)
def test_check_arguments(tool, arguments, problem):
    assert check_arguments(tool, arguments) == problem


async def test_registry_refuses_bad_arguments_before_running_the_tool():
    calls = []

    async def get_sections(*, tenant_id, parent_ids):
        calls.append(parent_ids)
        return {}

    registry = ToolRegistry(
        [Tool("get_sections", "", Permission.QUERY_RUN, get_sections)], max_calls=5
    )
    with pytest.raises(ToolError, match="more than 50 ids"):
        await registry.call(
            "get_sections",
            tenant_id="t",
            permissions=perms(SystemRole.EMPLOYEE),
            calls_so_far=0,
            arguments={"parent_ids": [str(i) for i in range(60)]},
        )
    await registry.call(
        "get_sections",
        tenant_id="t",
        permissions=perms(SystemRole.EMPLOYEE),
        calls_so_far=0,
        arguments={"parent_ids": ["p1"]},
    )
    assert calls == [["p1"]]


def test_time_is_used_for_fixed_windows():
    # Two keys in the same window are equal; the window rolls over with time.
    limit = Limit("x", 1, 60)
    key_now, _ = RateLimiter._key(limit, "u", "t")
    assert key_now.endswith(f":{int(time.time()) // 60}")


def test_markers_after_the_full_stop_stay_with_their_sentence():
    # Found by the Phase 12 evaluation: "…notice. [1] Next…" used to credit
    # [1] to the next sentence and mark the cited one "uncited".
    report = check_grounding(
        "Either party may terminate on 60 days' written notice. [1] "
        "Liability is capped at the fees paid in the preceding 12 months.[2]",
        BLOCKS,
    )
    assert report.score == 1.0 and [c.cited for c in report.claims] == [[1], [2]]


def test_markdown_answers_are_checked_line_by_line():
    # Structured answers (qa-v3 prompt): headings and "Label:" lines are
    # structure, bullets are claims, **bold** and list markers are ignored.
    answer = (
        "Either party may terminate on 60 days' written notice [1].\n\n"
        "### Liability\n"
        "Key points:\n"
        "- Liability is capped at the **fees paid** in the preceding **12 months** [2]\n"
        "1. Either party may terminate on 90 days' notice [1]"
    )
    report = check_grounding(answer, BLOCKS)
    assert [c.sentence for c in report.claims] == [
        "Either party may terminate on 60 days' written notice .",
        "Liability is capped at the fees paid in the preceding 12 months",
        "Either party may terminate on 90 days' notice",
    ]  # stored without the [n] markers
    assert [c.supported for c in report.claims] == [True, True, False]  # 90 isn't in [1]


def test_abbreviations_do_not_split_a_claim():
    report = check_grounding("The cap is about 12 months of fees (approx. one year) [2].", BLOCKS)
    assert len(report.claims) == 1 and report.claims[0].supported
