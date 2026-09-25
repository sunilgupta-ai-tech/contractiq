# API

Base path `/api/v1`. OpenAPI at `/docs` (disabled in production).

Success: `{"success": true, "data": …, "request_id": "…"}`
Error: `{"success": false, "error": {"code": "…", "message": "…", "details": {…}}, "request_id": "…"}`

| Method | Path | Phase | Status |
|---|---|---|---|
| GET | `/health` | 1 | live — liveness |
| GET | `/ready` | 1 | live — 200 ready/degraded, 503 not_ready |
| POST | `/auth/register` | 2 | live — new organization + its first ADMIN; returns a token pair (201) |
| POST | `/auth/login` | 2 | live — token pair; one generic 401 for every failure |
| POST | `/auth/refresh` | 2 | live — single-use refresh token → new pair; role re-read from the DB |
| GET | `/users/me` | 2 | live — any authenticated user |
| GET, POST | `/users` | 2 | live — ADMIN only (`user:manage`), own organization only |
| PATCH | `/users/{id}` | 2 | live — ADMIN only; name, role, active status (not your own role/status) |
| POST | `/documents/upload` | 3 | live — multipart `file` (+ optional `title`, `contract_type`, `counterparty`, `document_id` for a new version, `version_label`); 202 with document, version and job. ADMIN, LEGAL_MANAGER, ANALYST |
| GET | `/documents` | 3 | live — paginated; `status`, `contract_type`, `q` (title/counterparty search) |
| GET | `/documents/{id}`, `/documents/{id}/status` | 3 | live — detail with all versions; processing progress of the latest version |
| DELETE | `/documents/{id}` | 3 | live — 204; removes vectors, rows and files. ADMIN, LEGAL_MANAGER |
| GET | `/jobs/{id}` | 3 | live — job status, attempts, per-stage timings |
| POST | `/query` | 7 | live — cited answer over the tenant's contracts (hybrid search, rerank, small-to-big); see docs/rag.md |
| POST | `/contracts/summarize`, `/contracts/extract-clauses`, `/contracts/compare`, `/contracts/risk-analysis`, `/contracts/portfolio-summary` | 10 | 501 |

Every response carries `X-Request-ID`; send your own to correlate with upstream logs.
