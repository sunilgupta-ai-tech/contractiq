# DocuNexa AI

**Enterprise Multimodal Document Intelligence Platform** — agentic RAG with cited answers.

## What is DocuNexa AI?

DocuNexa AI is an enterprise multimodal document intelligence platform. It can process structured and unstructured documents such as PDFs, scanned PDFs, images, Word files and Excel files using OCR, vision models, RAG and Agentic AI. The system allows users to search, understand, compare, summarize and extract information from documents with grounded citations.

| Capability | Status |
|---|---|
| Digital PDFs (text, tables, embedded images) | ✅ Available |
| Scanned PDFs (OCR) | ✅ Available |
| Search & Q&A with page/section/clause citations | ✅ Available |
| Compare versions, summaries, risk review | ✅ Available |
| Word (.docx) and Excel (.xlsx) | ✅ Available |
| Images (.jpg, .png) and handwritten / register scans | ✅ Available |
| Legacy .doc / .xls | Not supported: save as .docx / .xlsx |

Upload documents (digital or scanned), ask questions across them, compare versions, and review risk — with every answer cited to page, section, clause and version.

> Formerly *ContractIQ*. Internal identifiers (repo, Docker services, database, `contractiq_*` metrics) keep the old name so existing data, dashboards and alerts keep working.

> Status: **Phase 19 — Duplicate documents complete** (content-hash detection per organization — never by file name, never across organizations; duplicates are refused before storage, processing or embedding with "This document already exists in your organization." and a link to the existing copy; a per-organization unique index makes simultaneous uploads safe; see [`docs/security.md`](docs/security.md)). **Phase 18 — Platform console complete** (separate super-admin sign-in and token audience; SUPER_ADMIN / read-only SUPPORT roles; every organization with status, plan, limits and usage; suspend with immediate session revocation; FREE / STARTER / BUSINESS / ENTERPRISE plans with per-organization limit overrides enforced on users, documents and storage; platform audit log; no access to organization content; see [`docs/platform.md`](docs/platform.md)). **Phase 17 — Roles & permissions complete** (built-in Admin / Manager / Employee / Viewer plus custom roles per organization built from a code-defined permission catalog; permission checks on every route from the signed token; no-escalation rules; role and status changes revoke tokens immediately; Team page for members and roles; the UI shows only permitted actions; see [`docs/security.md`](docs/security.md)). **Phase 16 — Word, Excel & image uploads complete** (.docx read as headings, lists, tables and Word's own page breaks; .xlsx sheet by sheet with header-repeating tables; JPG/PNG as one-page scans with EXIF rotation, OCR and a caption; weak OCR — handwriting, ruled registers — transcribed by the vision model, registers as tables; content-based upload checks refusing legacy, macro-enabled, password-protected and zip-bomb files; see [`docs/file-formats.md`](docs/file-formats.md)). **Phase 15 — Company isolation & document library complete** (PostgreSQL row-level security as a second tenant-isolation layer under the tenant-scoped repositories, for API requests and worker jobs; Documents library with All / PDF / Images / Word / Excel tabs and counts, search by title or file name, status filter, sorting and server-side paging, indexed for 10,000+ documents per organization; see [`docs/security.md`](docs/security.md) and [`docs/api.md`](docs/api.md)). **Phase 13 — Observability complete** (Prometheus metrics for HTTP, RAG stages, model calls, tokens, cost, answer outcomes and the worker pipeline; one trace per question to Langfuse or logs; per-call model logs; example alert rules; see [`docs/observability.md`](docs/observability.md)). **Phase 12 — Evaluation complete** (golden dataset over a generated sample MSA, end-to-end harness with retrieval, answer, citation and groundedness metrics, optional LLM judge, grounding-threshold calibration, JSON/Markdown reports and a baseline regression gate in CI; see [`docs/evaluation.md`](docs/evaluation.md)). **Phase 11 — Guardrails complete** (rate limits and failed-login throttling in Redis, hidden-character stripping, output sanitising, per-answer groundedness check with `flag`/`enforce` policy, agent tool-argument limits; see [`docs/guardrails.md`](docs/guardrails.md)). **Phase 10 — Contract analysis complete** (clause extraction with verified quotes and typed facts, cited executive summaries with key dates, rule-based risk findings, clause-aligned version/contract comparison, portfolio summary; cached per version, background analysis for large requests; see [`docs/contract-analysis.md`](docs/contract-analysis.md)). **Phase 9 — Multimodal complete** (images captioned by a vision model and tables summarised, so figures, signatures and tables are searchable; captions are their own chunks cited to the image's page region; Gemini by default, Ollama optional; see [`docs/multimodal.md`](docs/multimodal.md)). **Phase 8 — LangGraph agent complete** (`/query` default: follow-up rewriting, multi-part decomposition, evidence validation and bounded retries; `mode: "fast"` for single-pass; see [`docs/agentic-rag.md`](docs/agentic-rag.md)). **Phase 7 — Contract Q&A (RAG) complete** (`POST /query`: hybrid search, reranking, small-to-big context, verified citations; see [`docs/rag.md`](docs/rag.md)). **Phase 6 — Embeddings & Qdrant indexing complete** (Gemini by default, Ollama optional; dense + keyword vectors, tenant-isolated, version-aware; see [`docs/embeddings.md`](docs/embeddings.md)). **Phase 5 — Contract-aware chunking complete** (section/clause-aware parent + child chunks with metadata; see [`docs/chunking.md`](docs/chunking.md)). **Phase 4 — PDF processing & OCR complete** (text layer, tables, images, scanned-page OCR and layout labelling; see [`docs/pdf-processing.md`](docs/pdf-processing.md)). Phase 3 — Document upload complete. Phase 1 delivered the monorepo, FastAPI, PostgreSQL, Redis, Qdrant, worker, Docker, configuration, health checks, logging, full database schema, and the complete designed frontend. Phase 2 added registration, login, single-use refresh tokens, RBAC-protected user management and tenant-scoped audit logging. Phase 3 adds validated PDF upload, versioning, dedupe, storage, queued processing jobs, status polling and delete (see [`docs/api.md`](docs/api.md) and [`docs/security.md`](docs/security.md)). All planned API endpoints are implemented as of Phase 10 (see [`docs/api.md`](docs/api.md)).

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
make eval                                            # RAG quality on the golden dataset (docs/evaluation.md)
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
| 15 | Company isolation (row-level security) + document library | ✅ |
| 16 | Word, Excel and image uploads (.docx, .xlsx, .jpg, .png) + handwriting transcription | ✅ |
| 17 | Roles & permissions: built-in + custom roles, Team page | ✅ |
| 18 | Platform (super admin) console: organizations, status, plans and limits | ✅ |
| 19 | Tenant-specific duplicate document detection | ✅ |

The frontend runs on demo data (`NEXT_PUBLIC_USE_DEMO_DATA=true`) until each backend phase lands; the **System health** page always uses the live API.

---

*DocuNexa AI is an AI-assisted analysis tool and not a substitute for professional legal advice.*
