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
| POST | `/auth/refresh` | 2 | live — single-use refresh token → new pair; user, role and permissions re-read from the DB |
| GET | `/users/me` | 2 | live — any authenticated user |
| GET, POST | `/users` | 2 | live — ADMIN only (`user:manage`), own organization only |
| PATCH | `/users/{id}` | 2, 17 | live — `user:manage`; name, `role_id`, active status (not your own role/status, not a user with more access than you); revokes that user's tokens at once |
| * | `/platform/...` | 18 | live — platform console, separate sign-in and token audience; see [platform.md](platform.md) |
| GET | `/permissions` | 17 | live — the permission catalog (key, group, label, description) |
| GET | `/roles` | 17 | live — `user:manage` or `role:manage`; system roles + the organization's custom roles, with member counts |
| POST / PATCH / DELETE | `/roles`, `/roles/{id}` | 17 | live — `role:manage`; custom roles only, permissions within your own, never the role you hold; delete only when unused (409 otherwise); a permission change revokes the organization's tokens |
| POST | `/documents/upload` | 3, 16 | live — multipart `file` (PDF, JPG, PNG, .docx or .xlsx; checked by content, see [file-formats.md](file-formats.md)) (+ optional `title`, `contract_type`, `counterparty`, `document_id` for a new version, `version_label`); 202 with document, version and job. `document:upload` (Admin, Manager, Employee) |
| GET | `/documents` | 3, 15 | live — paginated library; `file_type` (PDF, IMAGE, WORD, EXCEL), `status` (repeatable), `contract_type`, `q` (title, counterparty or file name), `sort` (newest, oldest, name) |
| GET | `/documents/facets` | 15 | live — counts for the library tabs: `all` and `by_file_type`, under the same `status`/`q` filters |
| GET | `/documents/{id}`, `/documents/{id}/status` | 3 | live — detail with all versions; processing progress of the latest version |
| DELETE | `/documents/{id}` | 3 | live — 204; removes vectors, rows and files. `document:delete` (Admin, Manager) |
| GET | `/jobs/{id}` | 3 | live — job status, attempts, per-stage timings |
| POST | `/query` | 7–8 | live — cited answer over the tenant's contracts. `mode`: `agent` (default, LangGraph: rewrite, decompose, retry; docs/agentic-rag.md) or `fast` (single pass; docs/rag.md) |
| POST | `/contracts/extract-clauses` | 10 | live — `{document_id, version_id?, refresh?}`; one entry per standard topic: verified quote, typed facts, location. Cached per version (docs/contract-analysis.md) |
| POST | `/contracts/summarize` | 10 | live — same body; cited overview, obligations, key terms, key dates (incl. computed non-renewal deadline), risk counts |
| POST | `/contracts/compare` | 10 | live — `{left_version_id, right_version_id}`; clauses aligned by topic, `same`/`changed`/`missing` with fact-level notes and risk. Versions of one contract or two different contracts |
| POST | `/contracts/risk-analysis` | 10 | live — `{document_ids?}` or `{version_id}`; rule-based findings with evidence, most severe first; un-analysed documents are queued (`pending_document_ids`). Advisory |
| POST | `/contracts/portfolio-summary` | 10 | live — `{document_ids?}`; per-contract key terms and risk, upcoming dates across the portfolio |

Rate limits (Phase 11, [guardrails.md](guardrails.md)): `/query`, `/contracts/*`, `/documents/upload` and failed `/auth/login` attempts return 429 `RATE_LIMITED` with `Retry-After` when exceeded. `/query` responses include `groundedness` and `unsupported_claims`.

`/contracts/*` needs `analysis:run` (Admin, Manager, Employee, or a custom role with it). A document that has not finished processing returns 409; ids from another organisation return 404.

Every response carries `X-Request-ID`; send your own to correlate with upstream logs.
