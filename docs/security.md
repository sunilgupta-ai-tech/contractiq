# Security

Implemented in Phase 1:

* Settings refuse unsafe production config (default JWT secret, wildcard CORS, S3 without bucket). Secrets are `SecretStr` and never appear in reprs or logs; log records redact secret-like keys.
* bcrypt password hashing; JWTs carry `sub`, `tid` (tenant), `role`, `type`; refresh tokens rejected where access tokens are expected.
* RBAC matrix (`ROLE_PERMISSIONS`) and `require_permission()` dependency.
* Tenant-scoped repositories; cross-tenant reads return `NOT_FOUND` (no ID probing). Tested against real Postgres.
* Mandatory Qdrant tenant filter; tenant-prefixed cache keys and S3 object keys.
* Uniform error envelope; no stack traces or exception text to clients; dependency errors reported by class name only.
* Security headers on API and frontend; CORS allow-list; OpenAPI disabled in production; non-root containers.
* Local storage blocks path traversal.
* Prompt-injection: retrieved text wrapped in nonce-tagged untrusted blocks (documents cannot forge the closing tag) plus heuristic detection for flagging.

Implemented in Phase 2:

* Register / login / refresh endpoints. Passwords: at least 12 characters, at most 72 bytes (bcrypt's limit — rejected, never truncated).
* Login failures are indistinguishable: unknown email, wrong password and disabled account/organization return the same 401, and unknown emails still pay for a bcrypt comparison so timing doesn't reveal which emails exist.
* Refresh tokens are single-use: each `jti` is claimed atomically in Redis (key expires with the token). A replay returns 401. If Redis is unreachable, refresh fails closed with 503.
* Refresh re-reads the user from Postgres, so role changes and deactivation take effect within one access-token lifetime (30 min by default). Access tokens themselves stay stateless.
* User management is ADMIN-only and tenant-scoped; another organization's user IDs return `NOT_FOUND`. ADMINs cannot change their own role or active status (prevents locking an organization out).
* Audit log entries for `auth.register`, `auth.login`, `auth.login_failed`, `user.create`, `user.update` — IDs, field names, role/status values and client IP only; never passwords, tokens or names.

Implemented in Phase 3:

* Uploads accept PDFs only: `.pdf` name, a PDF-compatible declared type, and `%PDF-` magic bytes (a renamed executable is rejected). Empty files are rejected.
* Size limit (`MAX_UPLOAD_SIZE_MB`, default 50) enforced twice: a middleware rejects an oversized declared `Content-Length` before the body is read, and the route stops reading a chunked upload as soon as it passes the limit.
* The client's filename is cleaned (path parts and control characters removed) and used for display only; objects are stored at `tenants/{tenant}/documents/{doc}/{version}/original.pdf`, so a crafted name cannot influence the storage path. Storage keys are never returned by the API.
* Duplicate detection by SHA-256 is tenant-scoped, so it never reveals that another organization holds the same file.
* Documents, versions and jobs are read through tenant-scoped repositories; another organization's IDs return `NOT_FOUND`. Delete removes Qdrant points (through `tenant_filter`) before rows and files.
* `document.upload` and `document.delete` are audited (IDs, size, hash — no content).

Implemented in Phase 4:

* PDFs are parsed only in the worker (never the API process), in a thread with a page ceiling (`MAX_PDF_PAGES`) checked before any page is read, and per-page OCR timeouts.
* Password-protected and corrupt PDFs are rejected with a fixed user-facing message; exception text from parsers is logged, never shown to users.
* Derived files (parsed.json, images) are stored under the same tenant-prefixed path as the original and are removed with it.

Planned: rate limiting, including login throttling (Redis, Phase 11); AV scanning of uploads; tool authorization in the agent registry; output/citation validation (Phase 11); httpOnly-cookie sessions via a frontend BFF route (the frontend still holds the access token in memory).
