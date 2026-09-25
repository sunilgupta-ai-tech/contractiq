# ContractIQ

**Enterprise multimodal contract intelligence & agentic RAG platform.**
Upload contracts (digital or scanned), ask questions across them, compare versions, and review risk — with every answer cited to page, section, clause and version.

> Status: **Phase 2 — Authentication complete.** Phase 1 delivered the monorepo, FastAPI, PostgreSQL, Redis, Qdrant, worker, Docker, configuration, health checks, logging, full database schema, and the complete designed frontend. Phase 2 adds registration, login, single-use refresh tokens, RBAC-protected user management and tenant-scoped audit logging (see [`docs/security.md`](docs/security.md)). Later-phase API endpoints are registered (visible in OpenAPI) and return `501 NOT_IMPLEMENTED` with their phase number.

---

## Quick start (local)

```bash
cp .env.example .env
make up          # frontend, backend, worker, postgres, redis, qdrant (+ migrations)
```

| Service | URL |
|---|---|
| Frontend | http://localhost:3000 |
| API docs (OpenAPI) | http://localhost:8000/docs |
| Readiness | http://localhost:8000/api/v1/ready |
| Qdrant dashboard | http://localhost:6333/dashboard |

Run apps natively against containerised infrastructure:

```bash
make infra && make migrate
make backend-dev     # :8000
make worker-dev
make frontend-dev    # :3000
```

Local LLM: install [Ollama](https://ollama.com), then `ollama pull llama3.1:8b && ollama pull nomic-embed-text`. To use Gemini instead, set `LLM_PROVIDER=gemini` and `GEMINI_API_KEY` (backend only).

---

## Architecture

```text
Next.js ──► FastAPI (/api/v1) ──► PostgreSQL   users · orgs · documents · versions · jobs · audit
                │                 Redis        cache · rate limits · job queue (arq)
                │                 Qdrant       dense + sparse vectors, tenant-indexed payloads
                │                 Storage      local FS (dev) / S3 (prod)
                │                 LLM          Ollama (local) / Gemini (hosted) via provider interface
                └── enqueue ──► Worker ── parse → OCR → chunk → embed → index
```

* **Ingestion is asynchronous.** Uploads return immediately; the worker walks the pipeline and commits every stage to PostgreSQL, which is the source of truth for status (the queue is only transport).
* **Tenant isolation is structural.** Repositories are constructed with a tenant ID and cannot query without it; every Qdrant query goes through `tenant_filter()`, whose tenant condition callers cannot remove. The tenant ID comes from the signed JWT, never from request input or the LLM.
* **Health is split.** `/health` is liveness only; `/ready` probes Postgres, Redis, Qdrant (critical) and the worker heartbeat (non-critical) concurrently with timeouts.

See [`docs/architecture.md`](docs/architecture.md) and [`docs/deployment.md`](docs/deployment.md).

## Local → production

The same images run everywhere; only environment variables change.

| Concern | Local (Docker Compose) | Production (AWS) |
|---|---|---|
| PostgreSQL | `postgres:16` container | RDS PostgreSQL (Multi-AZ) |
| Redis | `redis:7` container | ElastiCache (`rediss://`) |
| Qdrant | `qdrant/qdrant` container | Qdrant Cloud or self-hosted on ECS/EKS (`QDRANT_API_KEY`) |
| Files | `/data/storage` volume | S3 (SSE, IAM task role — no static keys) |
| Secrets | `.env` | Secrets Manager → ECS task definition |
| API / worker / web | containers | ECS services behind an ALB; worker autoscaled on queue depth |
| Logs | console | JSON (`LOG_JSON=true`) → CloudWatch |

Production boot is guarded: the app refuses to start outside `development` with the example JWT secret, wildcard CORS, or S3 storage without a bucket.

## Repository layout

```text
frontend/        Next.js 15 · React 19 · TypeScript · Tailwind — app/, components/, features/, hooks/, lib/, services/, types/, utils/, tests/
backend/         FastAPI · SQLAlchemy 2 (async) · Alembic · Pydantic v2
  app/api/v1/        thin route handlers
  app/core/          config, logging, errors, middleware, security, DI
  app/db/            models (all tables) + tenant-scoped repositories
  app/services/      business logic (health live; others phased)
  app/rag, agents/, document_processing/, multimodal/, guardrails/, evaluation/, observability/
  app/llm/           provider abstraction (Ollama, Gemini)
  app/vectorstore/   Qdrant client, tenant filter, collection schema
  app/storage/       local / S3 object storage
  migrations/        Alembic
workers/         arq worker: ingestion pipeline with per-stage status + timings
infrastructure/  docker/, aws/, monitoring/
docs/            architecture, api, database, security, deployment, …
```

## Tests

```bash
make test                                            # backend unit tests
CONTRACTIQ_INTEGRATION=1 pytest backend/tests/integration   # needs `make infra && make migrate`
cd frontend && npm test                              # frontend unit tests
```

Covered today: error envelope and secret-free errors, readiness semantics, request IDs and security headers, JWT/bcrypt/RBAC matrix, production config guards, prompt-injection delimiting, retrieval metrics (Recall/Precision/MRR/NDCG), tenant filter invariants, path traversal, **cross-tenant repository isolation against real Postgres**, and worker success/failure paths.

## Roadmap

| Phase | Scope | Status |
|---|---|---|
| 1 | Foundation — monorepo, services, Docker, config, health, logging, schema, UI | ✅ |
| 2 | Auth — users, orgs, JWT, RBAC, tenant isolation | primitives + tests done |
| 3 | Upload — storage abstraction, upload API, jobs | storage + worker done |
| 4–6 | PDF/OCR → clause-aware chunking → embeddings + Qdrant | pipeline stages stubbed |
| 7–8 | Hybrid RAG + reranking + citations → LangGraph agent | state + prompts defined |
| 9–10 | Multimodal, comparison, risk, summaries | UI done (demo data) |
| 11–14 | Guardrails, evaluation, observability, production | partial (injection, metrics) |

The frontend runs on demo data (`NEXT_PUBLIC_USE_DEMO_DATA=true`) until each backend phase lands; the **System health** page always uses the live API.

---

*ContractIQ is an AI-assisted analysis tool and not a substitute for professional legal advice.*
