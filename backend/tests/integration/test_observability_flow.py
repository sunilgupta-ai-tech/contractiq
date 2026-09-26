"""
Phase 13 end to end: a real /query (PostgreSQL, Redis, Qdrant; fake models)
is counted in /metrics and exported as one trace built from its steps.

    CONTRACTIQ_INTEGRATION=1 pytest tests/integration
"""

import os
import time

import pytest

from tests.integration.conftest import auth, register
from tests.integration.test_query_flow import (  # noqa: F401 — `stack` is a fixture
    QUESTION,
    _index_contract,
    _tenant_of,
    stack,
)

pytestmark = pytest.mark.skipif(
    os.getenv("CONTRACTIQ_INTEGRATION") != "1", reason="set CONTRACTIQ_INTEGRATION=1"
)


class CapturingExporter:
    def __init__(self):
        self.traces = []

    async def export(self, trace):
        self.traces.append(trace)


def _metric(text: str, prefix: str) -> float:
    return sum(
        float(line.rsplit(" ", 1)[1]) for line in text.splitlines() if line.startswith(prefix)
    )


def test_query_is_measured_and_traced(stack, cleanup):  # noqa: F811 — pytest fixture
    client, settings, _ = stack
    exporter = CapturingExporter()
    client.app.state.resources._tracer = exporter
    tokens, _ = register(client, cleanup, "Observed Org")
    tenant = _tenant_of(client, tokens)
    _index_contract(settings, tenant)

    answered = 'contractiq_query_answers_total{mode="agent",outcome="answered"}'
    before = _metric(client.get("/metrics").text, answered)
    response = client.post("/api/v1/query", headers=auth(tokens), json={"question": QUESTION})
    assert response.status_code == 200, response.text
    request_id = response.headers["x-request-id"]

    text = client.get("/metrics").text
    assert _metric(text, answered) == before + 1
    assert 'contractiq_rag_stage_duration_seconds_count{stage="retrieve"}' in text
    assert 'route="/api/v1/query",status="200"' in text

    deadline = time.monotonic() + 2  # the export runs in the background
    while not exporter.traces and time.monotonic() < deadline:
        time.sleep(0.02)
    (trace,) = exporter.traces
    assert trace.name == "query" and trace.request_id == request_id and trace.tenant_id == tenant
    assert trace.session_id == response.json()["data"]["conversation_id"]
    assert trace.metadata["outcome"] == "answered" and trace.metadata["mode"] == "agent"
    assert [s.name for s in trace.spans][:1] == ["understand"] and trace.end is not None
    assert trace.input is None and trace.output is None  # no content by default
