#!/usr/bin/env bash
# PostgreSQL backup (Phase 23) for Docker Compose / single-host installs.
# On AWS, RDS automated backups and point-in-time restore do this job; see
# docs/reliability.md.
#
#   scripts/backup-postgres.sh                 # dump the compose `postgres` service
#   BACKUP_DATABASE_URL=postgresql://u:p@host:5432/db scripts/backup-postgres.sh  # any server
#
# Writes backups/postgres/<db>-<UTC timestamp>.dump (custom format, compressed),
# checks the archive is readable, and deletes dumps older than
# BACKUP_KEEP_DAYS (default 14). Dumps hold every organization's data:
# keep the directory private and encrypted, and copy it off the host.
set -euo pipefail

cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a

OUT_DIR="${BACKUP_DIR:-backups/postgres}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
DB="${BACKUP_DB:-${POSTGRES_DB:-contractiq}}"  # BACKUP_DB: another database on the same server
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
FILE="$OUT_DIR/$DB-$STAMP.dump"

mkdir -p "$OUT_DIR"
chmod 700 "$OUT_DIR"
umask 077

if [ -n "${BACKUP_DATABASE_URL:-}" ]; then
  # libpq doesn't understand SQLAlchemy's "+asyncpg" driver suffix.
  pg_dump --format=custom --no-owner "${BACKUP_DATABASE_URL/+asyncpg/}" > "$FILE"
  pg_restore --list "$FILE" > /dev/null
else
  docker compose exec -T postgres \
    pg_dump --format=custom --no-owner -U "${POSTGRES_USER:-contractiq}" -d "$DB" > "$FILE"
  docker compose exec -T postgres pg_restore --list < "$FILE" > /dev/null
fi

find "$OUT_DIR" -name "*.dump" -type f -mtime +"$KEEP_DAYS" -delete
echo "backup: $FILE ($(du -h "$FILE" | cut -f1))"
