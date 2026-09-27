#!/usr/bin/env bash
# PostgreSQL restore (Phase 23) for Docker Compose / single-host installs.
#
#   scripts/restore-postgres.sh backups/postgres/contractiq-20260927T000000Z.dump --yes
#
# Replaces the database's contents with the dump, in one transaction (all or
# nothing). Stop the API and worker first so nothing writes meanwhile:
#   docker compose stop backend worker
# Afterwards: `docker compose run --rm migrate` (a no-op if the dump is
# current), start backend and worker, then `python -m app.ops recover` and
# `python -m app.ops reindex --all` (docs/reliability.md explains why).
set -euo pipefail

cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a

FILE="${1:-}"
if [ -z "$FILE" ] || [ ! -f "$FILE" ]; then
  echo "usage: $0 <dump file> --yes" >&2
  exit 2
fi
if [ "${2:-}" != "--yes" ]; then
  echo "This replaces every row in the database with the dump. Re-run with --yes." >&2
  exit 2
fi

USER_NAME="${POSTGRES_USER:-contractiq}"
DB="${BACKUP_DB:-${POSTGRES_DB:-contractiq}}"  # BACKUP_DB: another database on the same server

# Roles are cluster-wide, so a dump never contains them. The row-level
# security role must exist before its grants and policies are restored.
PREPARE="DO \$\$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_tenant') THEN
    CREATE ROLE app_tenant NOLOGIN NOBYPASSRLS;
  END IF;
END \$\$;
GRANT app_tenant TO CURRENT_USER;"

if [ -n "${BACKUP_DATABASE_URL:-}" ]; then
  URL="${BACKUP_DATABASE_URL/+asyncpg/}"
  psql "$URL" -v ON_ERROR_STOP=1 -c "$PREPARE"
  pg_restore --clean --if-exists --no-owner --single-transaction --exit-on-error -d "$URL" "$FILE"
else
  docker compose exec -T postgres psql -U "$USER_NAME" -d "$DB" -v ON_ERROR_STOP=1 -c "$PREPARE"
  docker compose exec -T postgres pg_restore --clean --if-exists --no-owner \
    --single-transaction --exit-on-error -U "$USER_NAME" -d "$DB" < "$FILE"
fi
echo "restored: $FILE"
