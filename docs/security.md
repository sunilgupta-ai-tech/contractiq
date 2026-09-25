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

Planned: rate limiting, including login throttling (Redis, Phase 11); upload magic-byte checks and AV scanning (Phase 3); tool authorization in the agent registry; output/citation validation (Phase 11); httpOnly-cookie sessions via a frontend BFF route (the frontend still holds the access token in memory).
