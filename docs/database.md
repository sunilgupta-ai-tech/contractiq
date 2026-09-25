# Database

PostgreSQL 16, async SQLAlchemy 2, Alembic migrations (`backend/migrations`).

| Table | Purpose | Tenant-owned |
|---|---|---|
| `organizations` | Tenants | — |
| `users` | Accounts, bcrypt hash, role (`ADMIN`, `LEGAL_MANAGER`, `ANALYST`, `VIEWER`) | ✓ |
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
