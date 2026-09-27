# Database

PostgreSQL 16, async SQLAlchemy 2, Alembic migrations (`backend/migrations`).

| Table | Purpose | Tenant-owned |
|---|---|---|
| `organizations` | Tenants | — |
| `users` | Accounts, bcrypt hash, `role_id` → `roles` | ✓ |
| `organizations` | Phase 18: `status` (ACTIVE / SUSPENDED) with reason and time, `plan`, `max_users`, `max_documents`, `max_storage_mb` (NULL = unlimited) | ✓ (own) |
| `platform_admins`, `platform_audit_logs` | Phase 18: the operator side; no tenant grant | ✗ (unreachable) |
| `roles` | Phase 17: system roles (Admin, Manager, Employee, Viewer; `organization_id` NULL, fixed IDs) and each organization's custom roles; `permissions` is a JSON list from the code's catalog | ✓ (own + system) |
| `documents` | Logical contract, current status, current version | ✓ |
| `document_versions` | Each upload/amendment: storage key, sha256, pages, status, extraction metadata | ✓ |
| `processing_jobs` | Durable job state: stage, progress, attempts, timings, error | ✓ |
| `conversations`, `messages` | Chat history with citations, model, tokens, latency, trace ID | ✓ |
| `audit_logs` | Security-relevant actions (IDs only, no contract text) | ✓ |
| `evaluation_runs` | Golden-dataset runs: config snapshot + metrics | ✓ |

Conventions: UUID primary keys (non-enumerable), `created_at`/`updated_at` on every table, `organization_id` indexed on every tenant-owned table, deterministic constraint names for stable autogenerate diffs, enum types dropped explicitly on downgrade.

```bash
make migration m="add clause table"   # autogenerate
make migrate                          # apply
```

Production: RDS PostgreSQL, Multi-AZ, encrypted storage, automated backups, migrations run as a one-off ECS task before the new API revision receives traffic.
