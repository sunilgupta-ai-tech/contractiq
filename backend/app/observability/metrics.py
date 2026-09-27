"""
Prometheus metrics (Phase 13): latency, tokens, cost and outcomes per stage.

Exposed at GET /metrics (API) and on WORKER_METRICS_PORT (worker).

    HTTP        contractiq_http_requests_total{method,route,status}
                contractiq_http_request_duration_seconds{method,route}
    RAG         contractiq_rag_stage_duration_seconds{stage}
                contractiq_query_answers_total{mode,outcome}
                contractiq_answer_groundedness
    Models      contractiq_llm_calls_total{role,provider,model,outcome}
                contractiq_llm_call_duration_seconds{role,provider,model}
                contractiq_llm_tokens_total{role,provider,model,kind}
                contractiq_llm_cost_usd_total{role,provider,model}
                contractiq_embedding_texts_total{provider,model}
                contractiq_embedding_call_duration_seconds{provider,model}
    Guardrails  contractiq_rate_limited_total{limit}
    Worker      contractiq_documents_processed_total{outcome}
                contractiq_pipeline_stage_duration_seconds{stage}

Label discipline
----------------
Labels are low-cardinality only: route *templates* (never raw paths with
ids), model names, stage names, outcomes. Tenant and user ids are never
labels: every tenant would multiply every series, and ids in a metrics
system are hard to delete on request. Per-tenant usage is in the structured
logs and traces, which carry `tenant_id` (see llm_monitoring.py, tracing.py).

Multiple processes
------------------
`uvicorn --workers N` runs N processes, each with its own counters. When
PROMETHEUS_MULTIPROC_DIR is set (the backend image sets it), every process
writes its samples there and /metrics aggregates them. Without it (local
development, single process) the default in-process registry is used.
"""

from __future__ import annotations

import os

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
    multiprocess,
)

_MULTIPROC_DIR = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
if _MULTIPROC_DIR:
    os.makedirs(_MULTIPROC_DIR, exist_ok=True)

_LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120)
_MODEL_BUCKETS = (0.1, 0.25, 0.5, 1, 2, 4, 8, 15, 30, 60, 120)
_STAGE_BUCKETS = (0.1, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600, 1800)

HTTP_REQUESTS = Counter(
    "contractiq_http_requests_total", "HTTP requests.", ["method", "route", "status"]
)
HTTP_LATENCY = Histogram(
    "contractiq_http_request_duration_seconds",
    "HTTP request latency.",
    ["method", "route"],
    buckets=_LATENCY_BUCKETS,
)
RAG_STAGE_LATENCY = Histogram(
    "contractiq_rag_stage_duration_seconds",
    "Latency of each question-answering step (retrieve, rerank, context, generate, cite, ...).",
    ["stage"],
    buckets=_LATENCY_BUCKETS,
)
QUERY_ANSWERS = Counter(
    "contractiq_query_answers_total",
    "Answers by outcome: answered, not_found, withheld (grounding enforce), blocked.",
    ["mode", "outcome"],
)
ANSWER_GROUNDEDNESS = Histogram(
    "contractiq_answer_groundedness",
    "Groundedness score of generated answers (0-1).",
    buckets=(0.1, 0.25, 0.5, 0.75, 0.9, 1.0),
)
ANSWER_CACHE = Counter(
    "contractiq_answer_cache_total",
    "Answer cache lookups (Phase 21): hit = answered without a model call.",
    ["result"],
)
LLM_CALLS = Counter(
    "contractiq_llm_calls_total",
    "Model calls by outcome (ok, error, config_error, blocked).",
    ["role", "provider", "model", "outcome"],
)
LLM_LATENCY = Histogram(
    "contractiq_llm_call_duration_seconds",
    "Model call latency.",
    ["role", "provider", "model"],
    buckets=_MODEL_BUCKETS,
)
LLM_TOKENS = Counter(
    "contractiq_llm_tokens_total",
    "Tokens reported by the provider (kind = prompt | completion).",
    ["role", "provider", "model", "kind"],
)
LLM_COST = Counter(
    "contractiq_llm_cost_usd_total",
    "Estimated model cost in USD (only when LLM_PRICING is configured).",
    ["role", "provider", "model"],
)
EMBEDDING_TEXTS = Counter(
    "contractiq_embedding_texts_total",
    "Texts sent to the embedding provider (cache hits are not counted).",
    ["provider", "model"],
)
EMBEDDING_LATENCY = Histogram(
    "contractiq_embedding_call_duration_seconds",
    "Embedding call latency (one batch).",
    ["provider", "model"],
    buckets=_MODEL_BUCKETS,
)
RATE_LIMITED = Counter(
    "contractiq_rate_limited_total", "Requests refused by a rate limit.", ["limit"]
)
DOCUMENTS_PROCESSED = Counter(
    "contractiq_documents_processed_total",
    "Document versions processed by the worker (completed, rejected, failed).",
    ["outcome"],
)
MALWARE_SCANS = Counter(
    "contractiq_malware_scans_total",
    "Uploads checked by the malware scanner (clean, infected, error).",
    ["outcome"],
)
JOBS_RECOVERED = Counter(
    "contractiq_jobs_recovered_total",
    "Interrupted background jobs found by the recovery sweep (requeued or given up).",
    ["kind", "action"],
)
PIPELINE_STAGE_LATENCY = Histogram(
    "contractiq_pipeline_stage_duration_seconds",
    "Worker ingestion stage latency (parse, ocr, describe, chunk, embed, index).",
    ["stage"],
    buckets=_STAGE_BUCKETS,
)


def render_latest() -> tuple[bytes, str]:
    """(body, content type) for a scrape, aggregating all processes if needed."""
    if _MULTIPROC_DIR:
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)  # type: ignore[no-untyped-call]
        return generate_latest(registry), CONTENT_TYPE_LATEST
    return generate_latest(), CONTENT_TYPE_LATEST
