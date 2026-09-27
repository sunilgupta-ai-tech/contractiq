"""
Phase 13 tests: model monitoring (metrics, cost, logs), answer outcomes,
traces (steps, generations, Langfuse payload, exporters), the /metrics
endpoint, and provider wrapping in Resources.

Prometheus counters are process-global, so assertions compare values
before and after (deltas), never absolute numbers.
"""

import asyncio
import base64
import json
import logging

import httpx
import pytest
from prometheus_client import REGISTRY
from pydantic import SecretStr

from app.core.config import LLMProviderName, Settings
from app.core.resources import Resources
from app.guardrails.evidence_validator import UNVERIFIED_MESSAGE, GroundingReport
from app.llm.base import ChatMessage, LLMBlockedError, LLMConfigError, LLMError
from app.llm.resilient import ResilientLLM
from app.observability.llm_monitoring import (
    MonitoredEmbeddings,
    MonitoredLLM,
    estimate_cost,
    record_answer,
)
from app.observability.tracing import (
    Generation,
    LangfuseExporter,
    LogExporter,
    NoopExporter,
    Trace,
    build_exporter,
    configure_langsmith,
    current_trace,
    end_trace,
    export_in_background,
    langfuse_batch,
    record_generation,
    start_trace,
)
from app.rag.pipelines.qa import BLOCKED_MESSAGE, RagAnswer, Step
from tests.fake_embeddings import FakeEmbeddings
from tests.unit.test_rag import FakeLLM


def value(name, **labels):
    return REGISTRY.get_sample_value(name, labels) or 0.0


PRICING = {"fake-llm": {"input_per_mtok": 0.30, "output_per_mtok": 2.50}}


# --- Model monitoring ------------------------------------------------------------------------


def test_cost_needs_a_configured_price():
    assert estimate_cost(PRICING, "fake-llm", 1_000_000, 1_000_000) == pytest.approx(2.80)
    assert estimate_cost(PRICING, "fake-llm", None, 400) == pytest.approx(0.001)
    assert estimate_cost(PRICING, "other-model", 1000, 1000) is None


async def test_successful_calls_record_tokens_cost_latency_and_a_log_line(caplog):
    labels = {"role": "llm", "provider": "fake", "model": "fake-llm"}
    before = {
        "ok": value("contractiq_llm_calls_total", **labels, outcome="ok"),
        "prompt": value("contractiq_llm_tokens_total", **labels, kind="prompt"),
        "cost": value("contractiq_llm_cost_usd_total", **labels),
        "latency": value("contractiq_llm_call_duration_seconds_count", **labels),
    }
    llm = MonitoredLLM(FakeLLM("hello"), role="llm", pricing=PRICING)
    assert (llm.name, llm.model) == ("fake", "fake-llm")  # a drop-in provider
    with caplog.at_level(logging.INFO, logger="contractiq.llm"):
        result = await llm.generate([ChatMessage("user", "q", images=(b"png",))])

    assert result.text == "hello"
    assert value("contractiq_llm_calls_total", **labels, outcome="ok") == before["ok"] + 1
    assert value("contractiq_llm_tokens_total", **labels, kind="prompt") == before["prompt"] + 10
    assert value("contractiq_llm_cost_usd_total", **labels) > before["cost"]
    assert value("contractiq_llm_call_duration_seconds_count", **labels) == before["latency"] + 1
    (record,) = [r for r in caplog.records if r.getMessage() == "llm_call"]
    assert (record.prompt_tokens, record.completion_tokens, record.images) == (10, 5, 1)
    assert record.cost_usd == pytest.approx((10 * 0.30 + 5 * 2.50) / 1e6, abs=1e-6)
    # Sizes and numbers only: no prompt or answer text in the log record.
    assert not {"messages", "prompt", "content", "text"} & vars(record).keys()


@pytest.mark.parametrize(
    ("error", "outcome"),
    [
        (LLMError("503"), "error"),
        (LLMConfigError("key"), "config_error"),
        (LLMBlockedError("x"), "blocked"),
    ],
)
async def test_failed_calls_are_counted_by_outcome_and_re_raised(error, outcome):
    labels = {"role": "vision", "provider": "fake", "model": "fake-llm", "outcome": outcome}
    before = value("contractiq_llm_calls_total", **labels)
    with pytest.raises(type(error)):
        await MonitoredLLM(FakeLLM(error), role="vision").generate([ChatMessage("user", "q")])
    assert value("contractiq_llm_calls_total", **labels) == before + 1


async def test_embedding_texts_are_counted():
    labels = {"provider": "fake", "model": "hash-embed"}
    before = value("contractiq_embedding_texts_total", **labels)
    provider = MonitoredEmbeddings(FakeEmbeddings(8))
    assert (provider.name, provider.dimension) == ("fake", 8)
    assert len(await provider.embed(["a", "b", "c"])) == 3
    assert value("contractiq_embedding_texts_total", **labels) == before + 3


def _answer(**overrides):
    base = dict(
        answer="Notice is 60 days [1].",
        citations=[],
        insufficient_evidence=False,
        cited_fraction=1.0,
        steps=[Step("retrieve", "Hybrid search", "5", 12.0)],
        model="fake-llm",
        prompt_version="qa-v1",
        grounding=GroundingReport(score=1.0),
    )
    return RagAnswer(**(base | overrides))


@pytest.mark.parametrize(
    ("overrides", "withheld", "outcome"),
    [
        ({}, False, "answered"),
        ({"insufficient_evidence": True, "model": None}, False, "not_found"),
        ({"answer": BLOCKED_MESSAGE, "insufficient_evidence": True}, False, "blocked"),
        ({"answer": UNVERIFIED_MESSAGE, "insufficient_evidence": True}, True, "withheld"),
    ],
)
def test_answer_outcomes_and_stage_latency(overrides, withheld, outcome):
    before = value("contractiq_query_answers_total", mode="fast", outcome=outcome)
    stage_before = value("contractiq_rag_stage_duration_seconds_count", stage="retrieve")
    assert (
        record_answer(_answer(**overrides), mode="fast", withheld=withheld, latency_ms=20)
        == outcome
    )
    assert value("contractiq_query_answers_total", mode="fast", outcome=outcome) == before + 1
    assert (
        value("contractiq_rag_stage_duration_seconds_count", stage="retrieve") == stage_before + 1
    )


# --- Traces ----------------------------------------------------------------------------------------


async def test_model_calls_join_the_open_trace_only():
    record_generation(
        name="llm",
        model="m",
        duration_ms=5,
        prompt_tokens=1,
        completion_tokens=1,
        cost_usd=None,
        outcome="ok",
    )  # no trace: ignored
    trace = start_trace("query", user_id="u1")
    assert current_trace() is trace
    await MonitoredLLM(FakeLLM("a"), role="llm").generate([ChatMessage("user", "q")])
    trace.add_steps([Step("retrieve", "Search", "", 30.0), Step("generate", "Answer", "", 70.0)])
    assert end_trace() is trace and current_trace() is None

    (gen,) = trace.generations
    assert (gen.model, gen.prompt_tokens, gen.outcome) == ("fake:fake-llm", 10, "ok")
    first, second = trace.spans
    assert first.end == second.start  # steps are laid out back to back
    assert (second.end - first.start).total_seconds() == pytest.approx(0.1)


def test_langfuse_payload_has_ids_and_timings_but_no_content_by_default():
    trace = Trace("query", tenant_id="t1", request_id="r1", user_id="u1", session_id="c1")
    trace.metadata["mode"] = "fast"
    trace.add_steps([Step("retrieve", "Search", "5 candidates", 10.0)])
    trace.generations.append(
        Generation("llm", "gemini:flash", trace.start, trace.start, 100, 20, 0.001, "ok")
    )
    batch = langfuse_batch(trace)["batch"]
    kinds = [e["type"] for e in batch]
    assert kinds == ["trace-create", "span-create", "generation-create"]
    body = batch[0]["body"]
    assert body["id"] == trace.id and body["userId"] == "u1" and body["sessionId"] == "c1"
    assert body["metadata"]["tenant_id"] == "t1" and body["tags"] == ["tenant:t1"]
    assert body["input"] is None and body["output"] is None
    assert batch[2]["body"]["usage"] == {
        "input": 100,
        "output": 20,
        "unit": "TOKENS",
        "totalCost": 0.001,
    }
    assert all(e["body"].get("traceId", trace.id) == trace.id for e in batch)


async def test_langfuse_exporter_posts_with_basic_auth():
    seen = {}

    def handler(request):
        seen["url"], seen["auth"] = str(request.url), request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(207, json={"successes": [], "errors": []})

    exporter = LangfuseExporter(
        "https://lf.example/", "pk", "sk", transport=httpx.MockTransport(handler)
    )
    await exporter.export(Trace("query"))
    await exporter.aclose()
    assert seen["url"] == "https://lf.example/api/public/ingestion"
    assert base64.b64decode(seen["auth"].split()[1]) == b"pk:sk"
    assert seen["body"]["batch"][0]["type"] == "trace-create"


async def test_background_export_never_raises(caplog):
    class Broken:
        async def export(self, trace):
            raise ConnectionError("down")

    with caplog.at_level(logging.WARNING, logger="contractiq.tracing"):
        export_in_background(Broken(), Trace("query"))
        await asyncio.sleep(0.01)
    assert any(r.getMessage() == "trace_export_failed" for r in caplog.records)
    export_in_background(NoopExporter(), Trace("query"))  # no task at all


async def test_log_exporter_writes_one_trace_line(caplog):
    trace = Trace("query")
    trace.add_steps([Step("retrieve", "Search", "", 10.0)])
    trace.end = trace.spans[-1].end
    with caplog.at_level(logging.INFO, logger="contractiq.tracing"):
        await LogExporter().export(trace)
    (record,) = [r for r in caplog.records if r.getMessage() == "trace"]
    assert record.spans == [{"name": "retrieve", "ms": 10.0}] and record.duration_ms == 10.0


def test_exporter_selection():
    keys = {"langfuse_public_key": "pk", "langfuse_secret_key": "sk"}
    assert isinstance(build_exporter(Settings(tracing="auto")), NoopExporter)
    assert isinstance(build_exporter(Settings(tracing="auto", **keys)), LangfuseExporter)
    assert isinstance(build_exporter(Settings(tracing="log")), LogExporter)
    assert isinstance(build_exporter(Settings(tracing="langfuse")), NoopExporter)  # no keys
    assert isinstance(build_exporter(Settings(tracing="none", **keys)), NoopExporter)


def test_langsmith_settings_reach_the_environment(monkeypatch):
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    configure_langsmith(Settings(langsmith_tracing=False, langsmith_api_key="k"))
    import os

    assert "LANGSMITH_TRACING" not in os.environ
    configure_langsmith(Settings(langsmith_tracing=True, langsmith_api_key="k"))
    assert os.environ["LANGSMITH_TRACING"] == "true" and os.environ["LANGSMITH_API_KEY"] == "k"


# --- /metrics and wiring -----------------------------------------------------------------------------


async def test_metrics_endpoint_uses_route_templates(client):
    await client.get("/api/v1/documents/123e4567-e89b-12d3-a456-426614174000")
    await client.get("/no/such/path")
    response = await client.get("/metrics")
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/plain")
    text = response.text
    assert 'route="/api/v1/documents/{document_id}",status="401"' in text
    assert 'route="unmatched",status="404"' in text
    assert "123e4567" not in text  # ids never become labels


async def test_metrics_token_is_enforced(settings):
    from httpx import ASGITransport, AsyncClient

    from app.main import create_app

    app = create_app(settings.model_copy(update={"metrics_token": SecretStr("s3cret")}))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get("/metrics")).status_code == 401
        assert (
            await c.get("/metrics", headers={"Authorization": "Bearer wrong"})
        ).status_code == 401
        assert (
            await c.get("/metrics", headers={"Authorization": "Bearer s3cret"})
        ).status_code == 200


async def test_metrics_can_be_disabled(settings):
    from httpx import ASGITransport, AsyncClient

    from app.main import create_app

    app = create_app(settings.model_copy(update={"metrics_enabled": False}))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get("/metrics")).status_code == 404


async def test_resources_hand_out_monitored_providers(tmp_path):
    resources = Resources.create(
        Settings(
            llm_provider=LLMProviderName.OLLAMA,
            embedding_provider=LLMProviderName.OLLAMA,
            vision_provider=LLMProviderName.OLLAMA,
            local_storage_path=str(tmp_path),
        )
    )
    try:
        # Phase 21: the answer model is resilient (retry, fallback, breaker)
        # around a monitored provider.
        llm = resources.llm()
        assert isinstance(llm, ResilientLLM)
        assert isinstance(llm.primary, MonitoredLLM) and llm.primary.role == "llm"
        assert resources.light_llm() is llm  # no LLM_LIGHT_MODEL: one model
        assert isinstance(resources.vision(), MonitoredLLM) and resources.vision().role == "vision"
        assert isinstance(resources.embeddings(), MonitoredEmbeddings)
        assert resources.llm().model == "llama3.1:8b"
    finally:
        await resources.close()


def test_llm_pricing_parses_from_the_environment(monkeypatch):
    monkeypatch.setenv("LLM_PRICING", json.dumps(PRICING))
    assert Settings().llm_pricing == PRICING
