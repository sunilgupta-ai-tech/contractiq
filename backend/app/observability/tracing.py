"""
Request traces (Phase 13), keyed by request id and tenant id.

One trace per question: the steps the pipeline already times (retrieve,
rerank, context, generate, cite, or the agent's understand/validate/refine
...) become spans, and every model call made during the request becomes a
"generation" (model, tokens, latency, cost, outcome). Nothing in the RAG or
agent code had to change: steps come from the answer, generations from the
monitored providers (llm_monitoring.py), linked by a context variable.

Where traces go (TRACING):

    auto      Langfuse if LANGFUSE_PUBLIC_KEY/SECRET_KEY are set, else none
    langfuse  Langfuse ingestion API (POST {host}/api/public/ingestion)
    log       one structured `trace` log line (CloudWatch / Loki friendly)
    none      off

Privacy: by default traces carry ids, timings, sizes and scores — never
the question, the answer or contract text. LANGFUSE_CAPTURE_CONTENT=true
adds question and answer text; only enable it where your data-processing
terms with the tracing vendor allow client contract content.

LangSmith: the LangGraph agent is traced natively by LangSmith when
LANGSMITH_TRACING=true and LANGSMITH_API_KEY are set (see
`configure_langsmith`); that trace covers the agent graph's internals.

Export never blocks or fails a request: it runs in the background with a
short timeout, and errors are logged.
"""

from __future__ import annotations

import asyncio
import base64
import os
import uuid
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import httpx

from app.core.config import Settings
from app.core.logging import get_logger, request_id_ctx, tenant_id_ctx

logger = get_logger("contractiq.tracing")

EXPORT_TIMEOUT_S = 5.0


@dataclass
class Span:
    name: str
    start: datetime
    end: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Generation:
    name: str
    model: str
    start: datetime
    end: datetime
    prompt_tokens: int | None
    completion_tokens: int | None
    cost_usd: float | None
    outcome: str


@dataclass
class Trace:
    name: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    start: datetime = field(default_factory=lambda: datetime.now(UTC))
    end: datetime | None = None
    request_id: str | None = field(default_factory=request_id_ctx.get)
    tenant_id: str | None = field(default_factory=tenant_id_ctx.get)
    user_id: str | None = None
    session_id: str | None = None  # conversation id
    metadata: dict[str, Any] = field(default_factory=dict)
    input: str | None = None  # only with content capture on
    output: str | None = None
    spans: list[Span] = field(default_factory=list)
    generations: list[Generation] = field(default_factory=list)

    def add_steps(self, steps: list[Any]) -> None:
        """Pipeline steps (key, label, duration_ms, status, detail) as spans,
        laid out back to back from the trace start (steps run sequentially)."""
        cursor = self.start
        for step in steps:
            end = cursor + timedelta(milliseconds=step.duration_ms)
            self.spans.append(
                Span(
                    step.key,
                    cursor,
                    end,
                    {"label": step.label, "detail": step.detail, "status": step.status},
                )
            )
            cursor = end


_current: ContextVar[Trace | None] = ContextVar("current_trace", default=None)


def start_trace(name: str, **fields: Any) -> Trace:
    trace = Trace(name=name, **fields)
    _current.set(trace)
    return trace


def current_trace() -> Trace | None:
    return _current.get()


def end_trace() -> Trace | None:
    trace = _current.get()
    if trace is not None:
        trace.end = datetime.now(UTC)
        _current.set(None)
    return trace


def record_generation(
    *,
    name: str,
    model: str,
    duration_ms: float,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    cost_usd: float | None,
    outcome: str,
) -> None:
    """Called by the monitored providers; a no-op outside a trace."""
    trace = _current.get()
    if trace is None:
        return
    end = datetime.now(UTC)
    trace.generations.append(
        Generation(
            name=name,
            model=model,
            start=end - timedelta(milliseconds=duration_ms),
            end=end,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
            outcome=outcome,
        )
    )


# --- Exporters -------------------------------------------------------------------------------


class Exporter(Protocol):
    async def export(self, trace: Trace) -> None: ...


class NoopExporter:
    async def export(self, trace: Trace) -> None:
        return None


class LogExporter:
    async def export(self, trace: Trace) -> None:
        data = asdict(trace)
        logger.info(
            "trace",
            extra={
                "trace_id": trace.id,
                "trace_name": trace.name,
                "duration_ms": _ms(trace.start, trace.end),
                "spans": [
                    {"name": s["name"], "ms": _ms(s["start"], s["end"])} for s in data["spans"]
                ],
                "generations": [
                    {k: g[k] for k in ("model", "prompt_tokens", "completion_tokens", "outcome")}
                    for g in data["generations"]
                ],
                "trace_metadata": trace.metadata,
            },
        )


class LangfuseExporter:
    """Langfuse public ingestion API, over plain HTTP (no SDK dependency)."""

    def __init__(
        self,
        host: str,
        public_key: str,
        secret_key: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,  # tests inject a mock
    ) -> None:
        token = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
        self._client = httpx.AsyncClient(
            base_url=host.rstrip("/"),
            timeout=EXPORT_TIMEOUT_S,
            headers={"Authorization": f"Basic {token}"},
            transport=transport,
        )

    async def export(self, trace: Trace) -> None:
        response = await self._client.post("/api/public/ingestion", json=langfuse_batch(trace))
        if response.status_code >= 400:
            logger.warning("trace_export_rejected", extra={"status": response.status_code})

    async def aclose(self) -> None:
        await self._client.aclose()


def langfuse_batch(trace: Trace) -> dict[str, Any]:
    """The ingestion payload: one trace-create, then span- and generation-creates."""
    now = datetime.now(UTC).isoformat()

    def event(kind: str, body: dict[str, Any]) -> dict[str, Any]:
        return {"id": uuid.uuid4().hex, "timestamp": now, "type": kind, "body": body}

    tags = [t for t in (trace.tenant_id and f"tenant:{trace.tenant_id}",) if t]
    batch = [
        event(
            "trace-create",
            {
                "id": trace.id,
                "name": trace.name,
                "timestamp": trace.start.isoformat(),
                "userId": trace.user_id,
                "sessionId": trace.session_id,
                "input": trace.input,
                "output": trace.output,
                "tags": tags,
                "metadata": {
                    **trace.metadata,
                    "request_id": trace.request_id,
                    "tenant_id": trace.tenant_id,
                },
            },
        )
    ]
    batch += [
        event(
            "span-create",
            {
                "id": uuid.uuid4().hex,
                "traceId": trace.id,
                "name": span.name,
                "startTime": span.start.isoformat(),
                "endTime": span.end.isoformat(),
                "metadata": span.metadata,
            },
        )
        for span in trace.spans
    ]
    batch += [
        event(
            "generation-create",
            {
                "id": uuid.uuid4().hex,
                "traceId": trace.id,
                "name": gen.name,
                "model": gen.model,
                "startTime": gen.start.isoformat(),
                "endTime": gen.end.isoformat(),
                "usage": {
                    "input": gen.prompt_tokens,
                    "output": gen.completion_tokens,
                    "unit": "TOKENS",
                    **({"totalCost": gen.cost_usd} if gen.cost_usd is not None else {}),
                },
                "level": "DEFAULT" if gen.outcome == "ok" else "ERROR",
                "metadata": {"outcome": gen.outcome},
            },
        )
        for gen in trace.generations
    ]
    return {"batch": batch}


def build_exporter(settings: Settings) -> Exporter:
    mode = settings.tracing
    has_langfuse = bool(settings.langfuse_public_key and settings.langfuse_secret_key)
    if mode == "langfuse" or (mode == "auto" and has_langfuse):
        if not has_langfuse:
            logger.warning("tracing_langfuse_unconfigured")
            return NoopExporter()
        return LangfuseExporter(
            settings.langfuse_host or "https://cloud.langfuse.com",
            settings.langfuse_public_key.get_secret_value(),  # type: ignore[union-attr]
            settings.langfuse_secret_key.get_secret_value(),  # type: ignore[union-attr]
        )
    if mode == "log":
        return LogExporter()
    return NoopExporter()


_pending: set[asyncio.Task[None]] = set()


def export_in_background(exporter: Exporter, trace: Trace) -> None:
    """Fire and forget: a slow or failing tracing backend never delays or
    fails the user's request."""
    if isinstance(exporter, NoopExporter):
        return

    async def run() -> None:
        try:
            await asyncio.wait_for(exporter.export(trace), EXPORT_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001 — tracing is best effort
            logger.warning("trace_export_failed", extra={"error": type(exc).__name__})

    task = asyncio.get_running_loop().create_task(run())
    _pending.add(task)  # keep a reference until done (asyncio holds only weak ones)
    task.add_done_callback(_pending.discard)


def configure_langsmith(settings: Settings) -> None:
    """LangGraph/LangChain read LangSmith settings from the environment only.
    Settings may come from .env (not the process environment), so copy them
    across at startup when tracing is enabled."""
    if settings.langsmith_tracing and settings.langsmith_api_key:
        os.environ.setdefault("LANGSMITH_TRACING", "true")
        os.environ.setdefault("LANGSMITH_API_KEY", settings.langsmith_api_key.get_secret_value())


def _ms(start: Any, end: Any) -> float | None:
    if not isinstance(start, datetime) or not isinstance(end, datetime):
        return None
    return round((end - start).total_seconds() * 1000, 1)
