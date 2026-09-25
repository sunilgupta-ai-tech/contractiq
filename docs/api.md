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
| POST | `/documents/upload` | 3 | 501 |
| GET | `/documents`, `/documents/{id}`, `/documents/{id}/status` | 3 | 501 |
| DELETE | `/documents/{id}` | 3 | 501 |
| GET | `/jobs/{id}` | 3 | 501 |
| POST | `/query` | 7 | 501 |
| POST | `/contracts/summarize`, `/contracts/extract-clauses`, `/contracts/compare`, `/contracts/risk-analysis`, `/contracts/portfolio-summary` | 10 | 501 |

Every response carries `X-Request-ID`; send your own to correlate with upstream logs.
