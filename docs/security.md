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

Planned: rate limiting (Redis), upload magic-byte checks and AV scanning (Phase 3), tool authorization in the agent registry, output/citation validation (Phase 11), httpOnly-cookie sessions via a BFF route (Phase 2).
