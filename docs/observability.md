# Observability (Phase 13)

Three signals, all keyed so one question can be followed end to end:

| Signal | Where | Carries |
|---|---|---|
| **Logs** (Phase 1) | stdout, JSON with `LOG_JSON=true` | `request_id` and `tenant_id` on every line, plus Phase 13's `llm_call` / `rag_answer` / `trace` events |
| **Metrics** | `GET /metrics` (API), `:9101/metrics` (worker) | Prometheus counters and histograms; no tenant or user labels |
| **Traces** | Langfuse, or a `trace` log line | one trace per question: pipeline steps as spans, every model call as a generation |

Nothing in the RAG, agent, analysis or worker code had to be rewritten to get these. Model calls are measured by wrapping the providers once, in `Resources`. Traces reuse the step timings the pipeline already records. HTTP metrics live in the existing request middleware.

## Metrics

| Metric | Labels | Use |
|---|---|---|
| `contractiq_http_requests_total`, `…_http_request_duration_seconds` | method, route template, status | error rate and latency per endpoint |
| `contractiq_rag_stage_duration_seconds` | stage (retrieve, rerank, context, generate, cite, understand, validate, refine, …) | where answer time goes |
| `contractiq_query_answers_total` | mode, outcome (`answered`, `not_found`, `withheld`, `blocked`) | how often users get an answer |
| `contractiq_answer_groundedness` | — | distribution of Phase 11 groundedness scores |
| `contractiq_llm_calls_total` | role (`llm`/`vision`), provider, model, outcome | model error and safety-block rates |
| `contractiq_llm_call_duration_seconds` | role, provider, model | model latency |
| `contractiq_llm_tokens_total` | role, provider, model, kind (prompt/completion) | token usage |
| `contractiq_llm_cost_usd_total` | role, provider, model | spend (needs `LLM_PRICING`) |
| `contractiq_embedding_texts_total`, `…_embedding_call_duration_seconds` | provider, model | embedding volume (cache hits aren't sent, so aren't counted) |
| `contractiq_rate_limited_total` | limit | Phase 11 limits being hit |
| `contractiq_documents_processed_total` | outcome (`completed`, `rejected` = bad file, `failed` = our fault) | ingestion health |
| `contractiq_pipeline_stage_duration_seconds` | stage (parse, ocr, describe, chunk, embed, index) | ingestion time per stage |

**No tenant labels, by design.** Every tenant would multiply every series, and ids stored in a metrics system are hard to delete on request. Per-tenant usage and cost come from the `llm_call` logs and traces, which carry `tenant_id`.

**Several uvicorn processes:** the backend image sets `PROMETHEUS_MULTIPROC_DIR`. Each `--workers` process writes its samples there, and `/metrics` aggregates them. Local development (single process, no variable) uses the normal in-process registry. The worker serves its own metrics on `WORKER_METRICS_PORT` (9101; `0` = off).

**Securing `/metrics`:** it has no tenant data, but it shows traffic and cost patterns. Keep it off the public load balancer, or set `METRICS_TOKEN` and scrape with `Authorization: Bearer <token>`. `METRICS_ENABLED=false` removes the route.

Example Prometheus scrape config and alert rules (error rate, p95 `/query` latency, model errors, groundedness drop, ingestion failures, cost spike) are in `infrastructure/monitoring/prometheus/`.

## Cost

`LLM_PRICING` maps a model name to USD per million tokens:

```env
LLM_PRICING={"gemini-2.5-flash": {"input_per_mtok": 0.30, "output_per_mtok": 2.50}}
```

There are no built-in prices, because a stale hard-coded price is worse than none. Copy the current figures from the provider's price list for your tier. Unpriced models report tokens only; local Ollama models cost nothing per call. Cost shows up in `contractiq_llm_cost_usd_total`, in each `llm_call` log line (`cost_usd`), and on Langfuse generations.

## Model-call logs

Every LLM and vision call logs one `llm_call` line: role, provider, model, outcome, latency, prompt and completion tokens, cost, and image count. Every `/query` answer logs one `rag_answer` line: mode, outcome, model, prompt version, tokens, cited chunk ids, groundedness, review flags and latency. Request and tenant ids come from the logging context. Neither line contains prompt, question, answer or contract text.

## Traces

`TRACING` chooses where traces go:

| Value | Behaviour |
|---|---|
| `auto` (default) | Langfuse when `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are set, otherwise off |
| `langfuse` | Langfuse ingestion API (`LANGFUSE_HOST`, default `https://cloud.langfuse.com`), over plain HTTP with no SDK |
| `log` | one structured `trace` log line per question |
| `none` | off |

A trace is named `query`. It holds the user id, the conversation as its session, and `tenant:<id>` as a tag, and its metadata records mode, outcome, model, prompt version, groundedness and citation count. Spans are the pipeline's steps (agent steps in agent mode) and generations are the model calls made while answering. Export runs in the background with a 5-second timeout, so a slow or unreachable tracing backend never delays or fails an answer.

**Content is off by default.** Traces carry ids, timings, sizes and scores only. `LANGFUSE_CAPTURE_CONTENT=true` adds the question and the answer text. Enable it only where your data-processing terms with the tracing vendor allow client contract content, or self-host Langfuse.

**LangSmith:** set `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY` to get LangGraph's native traces of the agent graph's internals. Settings from `.env` are copied into the process environment at startup, which is where LangGraph reads them.

## Settings

`METRICS_ENABLED` (true), `METRICS_TOKEN` (unset), `WORKER_METRICS_PORT` (9101), `LLM_PRICING` ({}), `TRACING` (auto), `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`, `LANGFUSE_CAPTURE_CONTENT` (false), `LANGSMITH_TRACING` (false), `LANGSMITH_API_KEY`.
