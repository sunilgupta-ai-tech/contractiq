# Architecture

## Services

| Service | Responsibility | Scales on |
|---|---|---|
| `frontend` | Next.js UI. Talks only to the API; holds no secrets. | Requests |
| `backend` | FastAPI. Auth, tenant scoping, orchestration, query path. Never parses PDFs inline. | Requests / CPU |
| `worker` | arq consumer. Parse → OCR → chunk → embed → index. | Queue depth |
| `postgres` | Durable relational state and job status (source of truth). | — |
| `redis` | Cache, rate limits, queue transport, worker heartbeat. | — |
| `qdrant` | Vectors (dense + sparse) with tenant-indexed payloads. | Vectors / QPS |

## Request lifecycle

1. `RequestContextMiddleware` assigns/propagates `X-Request-ID`, adds security headers, logs latency.
2. Dependencies resolve settings, DB session and (Phase 2) the current user from the JWT. The tenant ID is placed in a context var so every log line carries it.
3. Handlers are thin: validate via Pydantic, call a service, return an `ApiResponse` envelope.
4. `AppError` subclasses map to the uniform error envelope; unexpected exceptions become `INTERNAL_ERROR` with no internals exposed.

## Ingestion lifecycle

`UPLOADED → QUEUED → PROCESSING → OCR_PROCESSING → CHUNKING → EMBEDDING → INDEXING → COMPLETED | FAILED`

Each transition is committed to `documents`, `document_versions` and `processing_jobs` so the UI can poll status. Stage timings are recorded in `processing_jobs.stage_timings_ms`. Indexing is delete-then-upsert keyed by `version_id`, making retries idempotent.

## Query lifecycle (Phases 7–8)

LangGraph: understand → select documents → hybrid retrieve (tenant filter) → rerank → extract clauses → validate evidence (retry ≤ 2) → answer → cite. Retrieved text is wrapped in nonce-tagged `<untrusted_document_*>` blocks; tools receive `tenant_id` from state, never from model output.

## Key decisions

* **Separate ingestion and query paths** — PDF processing is slow; queries must be fast.
* **PostgreSQL + Qdrant** — relational integrity vs. specialised vector search; neither does the other's job well.
* **One Qdrant collection, `tenant_id` payload index with `is_tenant=true`** — Qdrant's recommended multitenancy; cheaper than a collection per tenant.
* **Named dense + sparse vectors** — hybrid search in one query with server-side fusion.
* **Provider abstraction** — switch Ollama ↔ Gemini ↔ others by config.
* **Demo-data switch in the frontend service layer** — the UI is built against the real API types; switching to live data changes no components.
