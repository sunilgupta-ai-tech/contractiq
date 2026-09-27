# Reliability: failures, recovery and backups (Phase 23)

DocuNexa AI keeps durable state in two places: **PostgreSQL** (every row) and **object storage** (original files and everything derived from them: `parsed.json`, `chunks.json`, images and analyses). Everything else can be rebuilt from these two:

| System | Holds | If it is lost |
|---|---|---|
| PostgreSQL | organizations, users, documents, versions, jobs, audit, usage | **restore from backup** (below) |
| Object storage (S3 / local) | files and derived files per tenant | S3 versioning + backups; local installs must back up the volume |
| Qdrant | vectors, rebuilt from `chunks.json` | restore a snapshot, or **reindex** |
| Redis | job queue, caches, rate-limit windows, refresh-token and revocation markers | nothing to restore; jobs are **recovered from PostgreSQL** |

## Interrupted jobs: automatic recovery

A `ProcessingJob` row is the source of truth for each document job, and the arq queue in Redis is only transport. The worker runs a **recovery sweep** every `JOB_RECOVERY_INTERVAL_MIN` (5) minutes, and once when it starts:

| Situation | Detected as | Action |
|---|---|---|
| Worker crashed or was killed mid-job, and arq gave up | `RUNNING` for longer than `JOB_STALE_RUNNING_S` (40 min, longer than the 30-minute job timeout), and arq no longer holds the job | queued again |
| Redis lost the queue (restart without persistence, failover, flush) | `PENDING` for longer than `JOB_STALE_PENDING_S` (15 min), and arq doesn't have it | queued again |
| A job keeps getting interrupted (e.g. a file that kills the worker) | started `JOB_RECOVERY_MAX_ATTEMPTS` (5) times | marked **FAILED**: "Processing was interrupted repeatedly… upload the document again" |
| Organization deletion lost | `DELETING` for longer than 40 min, and the deletion job isn't queued | deletion queued again (erasure is idempotent) |
| Long backlog, slow OCR | arq still holds the job (queued, deferred or running) | **left alone** |

The sweep never runs a job twice at once. It only requeues work that arq no longer holds, and it locks the rows it handles (`SKIP LOCKED`), so overlapping sweeps are safe. A requeued job gets a fresh arq id (`<job id>:recovery-<n>`), because arq keeps a finished run's result under the old id for 24 hours and would ignore it. Processing is idempotent: vectors are replaced per version, and files are overwritten, not duplicated. Duplicate *uploads* are refused separately (Phase 19).

Metric: `contractiq_jobs_recovered_total{kind, action}`. A steady non-zero rate of `action="fail"` means workers are dying on some documents. Check the worker's memory limit (`docs/production-scale.md`).

Run a sweep by hand, e.g. right after Redis came back:

```bash
make recover-jobs                                     # = python -m app.ops recover
docker compose exec backend python -m app.ops recover --dry-run   # show, change nothing
docker compose exec backend python -m app.ops status              # jobs, queue, worker, vectors
```

On ECS, run the same commands as a one-off task with the backend task definition (command override).

## Runbooks

### Worker crash

Nothing to do. The orchestrator restarts the container, arq retries the job (up to 3 tries), and the sweep catches anything arq gave up on. If one document fails every time, it ends as FAILED with a message, and the other documents are unaffected.

### Redis failure

What happens while Redis is down:
- The API stays up. `/ready` reports not ready, so the load balancer holds traffic until Redis is back.
- Uploads are refused with "could not be queued", and the user uploads again.
- Rate limits fail open. Revocation markers can't be read, so a role change applies within one access-token lifetime (30 min) instead of at once.

After Redis comes back **empty**:
1. Wait one sweep (≤ 5 min), or run `make recover-jobs`. Queued and interrupted document jobs, and organization deletions, are queued again from PostgreSQL.
2. Caches refill on their own: embeddings, captions, answers and analysis fingerprints. The first re-embeddings cost model calls.
3. Sessions: refresh-token "used" markers and revocation markers are gone. Revocations older than the access-token lifetime no longer matter. If users were suspended or roles removed in the last 30 minutes before the loss, **rotate `JWT_SECRET_KEY`**, which signs everyone out.

Production: ElastiCache with Multi-AZ and automatic failover (`docs/deployment.md`). Nothing in Redis needs a backup.

### Database failure

**AWS (RDS):** automated backups with point-in-time restore (set a retention of 7–35 days). Restore to a *new* instance at a time just before the incident, point `DATABASE_URL` (Secrets Manager) at it, and roll the services. Multi-AZ covers instance and AZ failure without a restore.

**Docker Compose / single host:**

```bash
make backup-db                     # backups/postgres/<db>-<UTC time>.dump, keeps 14 days
docker compose stop backend worker
make restore-db file=backups/postgres/contractiq-20260927T020000Z.dump
docker compose run --rm migrate    # no-op if the dump is current
docker compose start backend worker
```

- `scripts/backup-postgres.sh` runs `pg_dump` in custom format and checks that the archive is readable. Schedule it with cron (e.g. hourly) and copy `backups/` off the host. The dumps hold every organization's data, so keep them encrypted, and they are git-ignored.
- `scripts/restore-postgres.sh` restores in **one transaction** (all or nothing) and needs `--yes`. It first creates the row-level-security role `app_tenant`: roles are server-wide, so a dump never contains them, and without the role the policies can't be restored.
- Either script works against another server with `BACKUP_DATABASE_URL=postgresql://…`, or against another database with `BACKUP_DB=…`.

After a restore to an **earlier point in time**:
1. `python -m app.ops recover`: jobs that were running at backup time are queued again.
2. Documents uploaded after the backup have files in storage but no rows. Users upload them again. The orphaned files sit under `tenants/<org>/documents/<id>/`.
3. Vectors of documents deleted after the backup time are still in Qdrant, but the database no longer knows them. Run `python -m app.ops reindex --all`, and if in doubt, recreate the collection first (below).

### Vector database (Qdrant) failure

Two ways back:

| | Snapshot restore | Reindex |
|---|---|---|
| Command | `python -m app.ops restore-snapshot <key> --yes` | `python -m app.ops reindex --all` (or `--org ID`) |
| Speed | minutes (a file copy) | proportional to corpus size |
| Cost | none | embedding calls for texts no longer in the Redis embedding cache |
| Data | as of the snapshot. Reindex documents processed after it | always complete and current |

Snapshots: `make qdrant-snapshot` (= `python -m app.ops snapshot --keep 3`) asks Qdrant for a snapshot. It copies the file into object storage under `backups/qdrant/<collection>/`, streamed through disk and never whole in memory, and keeps the newest 3 on the Qdrant server. Schedule it daily. Keep `backups/` retention at or below 30 days: a snapshot still holds vectors of documents and organizations deleted after it was taken, and "delete" must eventually mean deleted.

Reindex queues one `reembed_tenant` job per organization. It rebuilds each processed version's vectors from its stored `chunks.json`, with no parsing or OCR, and recreates the collection first if it is missing.

**Qdrant Cloud:** enable the cluster's automatic backups as well. The commands above work the same against it (`QDRANT_URL`, `QDRANT_API_KEY`).

### API and model failures

Covered in Phase 21 (`docs/production-scale.md`): retries with backoff for 429/5xx/timeouts, a fallback model, and a circuit breaker per model. Consistent error envelopes and timeouts are covered in `docs/guardrails.md` and `docs/api.md`.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `JOB_RECOVERY_ENABLED` | `true` | run the sweep in the worker |
| `JOB_RECOVERY_INTERVAL_MIN` | `5` | minutes between sweeps |
| `JOB_STALE_PENDING_S` | `900` | a queued job untouched this long may be lost |
| `JOB_STALE_RUNNING_S` | `2400` | a running job untouched this long may be lost (keep above the 30-min job timeout) |
| `JOB_RECOVERY_MAX_ATTEMPTS` | `5` | starts before a job is given up as FAILED |
