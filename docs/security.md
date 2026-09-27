# Security

Implemented in Phase 1:

* Settings refuse unsafe production config (default JWT secret, wildcard CORS, S3 without bucket). Secrets are `SecretStr` and never appear in reprs or logs; log records redact secret-like keys.
* bcrypt password hashing; JWTs carry `sub`, `tid` (tenant), `aud` (`docunexa:tenant`), `role`, `rid` (role id), `perms`, `ts`, `type`; refresh tokens rejected where access tokens are expected, and tokens for another audience (the platform admin API) are rejected.
* **Roles and permissions (Phase 17).** The permission catalog is in code (`Permission`); roles are rows in `roles`: four built-in roles (Admin, Manager, Employee, Viewer) shared by every organization and locked, plus custom roles per organization. Every route checks a permission with `require_permission()`; the permissions come from the signed token. No escalation: a role can only contain permissions its author holds, nobody edits the role they hold, and nobody changes a user who has more access than they do. A role in use cannot be deleted.
* **Platform console (Phase 18).** Platform admins are a separate identity (own table, sign-in and `docunexa:platform` token audience); tenant and platform tokens are refused by each other's APIs. SUPPORT is read-only; SUPER_ADMIN changes. The console returns account metadata and counts, never document content. Suspending an organization revokes all its sessions at once and blocks refresh and sign-in (403 `ORGANIZATION_SUSPENDED`). Plan limits return 403 `PLAN_LIMIT_REACHED`. Every console action is in `platform_audit_logs`; the tenant role has no grant on the platform tables. See [platform.md](platform.md).
* **Immediate revocation.** Changing a user's role or active status, or a role's permissions, writes a "valid after" marker in Redis for the user or organization; every request compares the token's `ts` with it (one MGET) and a stale token gets 401, so the client refreshes and receives the current permissions (or is refused). If Redis is unreachable the check is skipped and logged; refresh still re-reads the database ([app/core/sessions.py](../backend/app/core/sessions.py)).
* Tenant-scoped repositories; cross-tenant reads return `NOT_FOUND` (no ID probing). Tested against real Postgres.
* **PostgreSQL row-level security (Phase 15)** as a second, independent layer. API requests and worker jobs bind their database session to the tenant in the signed token (or the job's row); every transaction then runs as the `app_tenant` role with `app.tenant_id` set, and the `tenant_isolation` policy on every table with `organization_id` (plus `organizations` itself) limits reads *and* writes to that tenant. A query that forgets its filter still returns only the caller's rows; a write into another tenant fails. Settings are transaction-local, so a pooled connection never carries one tenant into the next request, and with no tenant set the policies match nothing (fail closed). Sign-in, registration and token refresh run before a tenant is known and use the connection's own role. A test fails if a new tenant table is added without a policy ([app/db/tenancy.py](../backend/app/db/tenancy.py), migration `7c1d4e2a9b30`).
* Mandatory Qdrant tenant filter; tenant-prefixed cache keys and S3 object keys.
* Uniform error envelope; no stack traces or exception text to clients; dependency errors reported by class name only.
* Security headers on API and frontend; CORS allow-list; OpenAPI disabled in production; non-root containers.
* Local storage blocks path traversal.
* Prompt-injection: retrieved text wrapped in nonce-tagged untrusted blocks (documents cannot forge the closing tag) plus heuristic detection for flagging.

Implemented in Phase 2:

* Register / login / refresh endpoints. Passwords: at least 12 characters, at most 72 bytes (bcrypt's limit — rejected, never truncated).
* Login failures are indistinguishable: unknown email, wrong password and disabled account/organization return the same 401, and unknown emails still pay for a bcrypt comparison so timing doesn't reveal which emails exist.
* Refresh tokens are single-use: each `jti` is claimed atomically in Redis (key expires with the token). A replay returns 401. If Redis is unreachable, refresh fails closed with 503.
* Refresh re-reads the user, role and organization from Postgres, so a new token always carries current permissions.
* User management needs `user:manage` and is tenant-scoped; another organization's user or custom-role IDs return `NOT_FOUND` (roles are also under row-level security: a tenant reads the system roles and its own). Nobody can change their own role or active status (prevents locking an organization out).
* Audit log entries for `auth.register`, `auth.login`, `auth.login_failed`, `user.create`, `user.update`, `role.create`, `role.update`, `role.delete` — IDs, field names, role/status values and client IP only; never passwords, tokens or names.

Implemented in Phase 3:

* Uploads accept PDFs only: `.pdf` name, a PDF-compatible declared type, and `%PDF-` magic bytes (a renamed executable is rejected). Empty files are rejected.
* Size limit (`MAX_UPLOAD_SIZE_MB`, default 50) enforced twice: a middleware rejects an oversized declared `Content-Length` before the body is read, and the route stops reading a chunked upload as soon as it passes the limit.
* The client's filename is cleaned (path parts and control characters removed) and used for display only; objects are stored at `tenants/{tenant}/documents/{doc}/{version}/original.pdf`, so a crafted name cannot influence the storage path. Storage keys are never returned by the API.
* Phase 16 uploads are recognised from their bytes, not their name: PDF signature, JPEG/PNG signature plus a decode check (80-megapixel cap against decompression bombs), and for .docx/.xlsx a ZIP with the right OOXML parts. Refused: legacy and password-protected Office files (OLE container), macro-enabled files and any OOXML carrying `vbaProject.bin`, and ZIPs over 10,000 entries or 512 MB uncompressed. Originals are stored as `original.<ext>`, never under the client's name. Text transcribed from images is wrapped like any document text: the vision prompt treats the image as data, never as instructions.
* **Document-level access (Phase 20).** Inside an organization a document is either visible to everyone with `document:read` (`ORGANIZATION`) or `RESTRICTED` to its uploader, users and roles granted access (`document_grants`, under row-level security), and holders of `document:read_all` (Admin). The rule is one SQL condition applied by the document and version repositories, which require an explicit access scope (`DocumentAccess`; the worker uses `system()`), so the library, counts, detail, status, jobs, delete, new versions, analysis and the question scope all agree; a hidden document is `NOT_FOUND`. **RAG:** the tenant's hidden document ids are read from the database per question and excluded inside the Qdrant search (`must_not`), and their parents are dropped from context, so no chunk of a hidden document can reach the model. Managing access needs `document:share` (Admin, Manager) or being the uploader; grants may only name users and roles of the organization. A duplicate of a hidden document is refused without saying where it is.
* **Ingest-time injection scan (Phase 20).** Every child chunk is scanned for instruction-like text (override, role hijack, forged delimiters, exfiltration, tool abuse). Nothing is removed — document text always reaches the model as untrusted data — but the count is stored (`extraction_metadata.injection`) and shown on the document, so a planted file is visible.
* **Duplicate documents (Phase 19)** are detected by the SHA-256 of the uploaded bytes, never by file name (the same name with different content is a new document), and only within the caller's organization (repository scope, row-level security, and a partial unique index on `(organization_id, sha256)` for versions that did not fail). A duplicate is refused before anything is stored, processed or embedded, with 409 `DUPLICATE_DOCUMENT` "This document already exists in your organization." and a pointer to the organization's own copy. The same file in two organizations is two independent documents; neither can learn of the other. The unique index makes simultaneous uploads of one file safe, and a failed upload can be uploaded again.
* Documents, versions and jobs are read through tenant-scoped repositories; another organization's IDs return `NOT_FOUND`. Delete removes Qdrant points (through `tenant_filter`) before rows and files.
* `document.upload` and `document.delete` are audited (IDs, size, hash — no content).

Implemented in Phase 4:

* PDFs are parsed only in the worker (never the API process), in a thread with a page ceiling (`MAX_PDF_PAGES`) checked before any page is read, and per-page OCR timeouts.
* Password-protected and corrupt PDFs are rejected with a fixed user-facing message; exception text from parsers is logged, never shown to users.
* Derived files (parsed.json, images) are stored under the same tenant-prefixed path as the original and are removed with it.

Implemented in Phase 8:

* Agent tools are reached only through a registry that checks each tool's permission against the caller's permissions, injects `tenant_id` itself (arguments may not set it), and enforces a per-question call budget, retry and step limits, and an overall timeout.

Implemented in Phase 11 (details in [guardrails.md](guardrails.md)):

* Rate limits in Redis: `/query` per user and per organisation, `/contracts/*` and uploads per user. Returns 429 with `Retry-After`; checked after authorization, so refused requests don't consume allowances. Fails open (logged) if Redis is down.
* Login throttling on *failed* attempts per (IP, email) and per IP. Keys hold hashes, never email addresses.
* Questions are Unicode-normalised and stripped of zero-width, bidi-override and control characters (hidden-instruction smuggling).
* Model output is sanitised before users see it: echoed delimiter/system tags removed, secret-like tokens (API keys, JWT/bearer tokens, private keys) redacted, length capped.
* Groundedness check on every answer (numbers must appear in the cited evidence; key terms must overlap). Reported as `groundedness` / `unsupported_claims`; `GROUNDING_MODE=enforce` withholds unverifiable answers.
* Agent tool arguments are validated (size and type limits, no unknown arguments) before any tool runs.

Implemented in Phase 13 ([observability.md](observability.md)):

* Metrics carry no tenant or user labels; `/metrics` sits outside the API, is hidden from OpenAPI, and can require `METRICS_TOKEN` (compared in constant time).
* Model-call logs and traces record ids, sizes, timings and scores, never prompt, question, answer or contract text. Sending content to Langfuse is an explicit opt-in (`LANGFUSE_CAPTURE_CONTENT`).
* Tracing export runs in the background with a timeout; a failing tracing backend cannot affect requests.

Planned: AV scanning of uploads; httpOnly-cookie sessions via a frontend BFF route (the frontend still holds the access token in memory).
