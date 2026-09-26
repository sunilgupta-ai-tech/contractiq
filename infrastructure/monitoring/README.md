# Monitoring

* Logs: JSON to stdout (`LOG_JSON=true`) with `request_id` and `tenant_id` on every line.
* Health: `/api/v1/health` (liveness), `/api/v1/ready` (dependency readiness incl. worker heartbeat).
* Metrics (Phase 13): Prometheus at `/metrics` (API) and `:9101/metrics` (worker). Example scrape config and alert rules in `prometheus/`.
* Traces (Phase 13): one per question, to Langfuse (`TRACING`, `LANGFUSE_*`) or a `trace` log line; LangSmith for LangGraph internals.
* Model usage and cost: `llm_call` / `rag_answer` log lines and `contractiq_llm_*` metrics (`LLM_PRICING` for cost).

See [docs/observability.md](../../docs/observability.md).
