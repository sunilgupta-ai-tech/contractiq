"""
Phase 11 guardrails end to end, against real PostgreSQL, Redis and Qdrant:
login throttling, per-user query limits, and the groundedness report on a
real /query answer.

    CONTRACTIQ_INTEGRATION=1 pytest tests/integration
"""

import os
import uuid

import anyio
import pytest
from fastapi.testclient import TestClient
from redis.asyncio import Redis

from app.core.config import Settings
from app.guardrails.input_guardrails import login_limits, subject_hash
from app.main import create_app
from app.vectorstore.qdrant import create_qdrant
from tests.fake_embeddings import FakeEmbeddings
from tests.integration.conftest import PASSWORD, auth, register
from tests.integration.test_query_flow import QUESTION, ScriptedLLM, _index_contract, _tenant_of

pytestmark = pytest.mark.skipif(
    os.getenv("CONTRACTIQ_INTEGRATION") != "1", reason="set CONTRACTIQ_INTEGRATION=1"
)


@pytest.fixture
def stack():
    settings = Settings(
        qdrant_collection=f"test_guard_{uuid.uuid4().hex[:10]}",
        login_max_failures=2,
        rate_limit_query_per_minute=1,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        resources = app.state.resources
        resources._embeddings = FakeEmbeddings(768)
        resources._llm = ScriptedLLM()
        yield client, settings

    async def drop():
        qdrant = create_qdrant(settings)
        await qdrant.delete_collection(settings.qdrant_collection)
        await qdrant.close()

    anyio.run(drop)


def _forget_login_counters(settings: Settings, email: str) -> None:
    """Login counters are global (no tenant yet at sign-in); remove this test's."""

    async def run():
        redis = Redis.from_url(settings.redis_url, decode_responses=True)
        for limit in login_limits(settings):
            async for key in redis.scan_iter(match=f"ciq:global:rl:{limit.name}:*"):
                if subject_hash("testclient", email) in key:
                    await redis.delete(key)
        await redis.aclose()

    anyio.run(run)


def test_failed_logins_are_throttled_per_email(stack, cleanup):
    client, settings = stack
    _, email = register(client, cleanup, "Throttle Org")
    try:

        def login(password):
            return client.post("/api/v1/auth/login", json={"email": email, "password": password})

        assert [login("wrong-password-1").status_code for _ in range(2)] == [401, 401]
        blocked = login(PASSWORD)  # even the right password waits out the window
        assert blocked.status_code == 429
        assert int(blocked.headers["Retry-After"]) <= settings.login_window_s
        assert blocked.json()["error"]["code"] == "RATE_LIMITED"
    finally:
        _forget_login_counters(settings, email)


def test_queries_are_limited_per_user_and_answers_carry_groundedness(stack, cleanup):
    client, settings = stack
    tokens, _ = register(client, cleanup, "Grounding Org")
    _index_contract(settings, _tenant_of(client, tokens))

    first = client.post("/api/v1/query", headers=auth(tokens), json={"question": QUESTION})
    assert first.status_code == 200, first.text
    data = first.json()["data"]
    # "Notices must be given in writing [1]." is in clause 8.3's text.
    assert data["groundedness"] == 1.0 and data["unsupported_claims"] == []

    second = client.post("/api/v1/query", headers=auth(tokens), json={"question": QUESTION})
    assert second.status_code == 429 and "Retry-After" in second.headers
    # Limits are per user: another user is not affected.
    other, _ = register(client, cleanup, "Grounding Org 2")
    assert (
        client.post("/api/v1/query", headers=auth(other), json={"question": QUESTION}).status_code
        == 200
    )
