#!/usr/bin/env bash
# Render (Phase 26): migrate, then run the API and the worker side by side.
# If either stops, the container exits so Render restarts it.
set -euo pipefail
cd /srv

alembic upgrade head

arq worker.main.WorkerSettings &
uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers &

wait -n
exit 1
