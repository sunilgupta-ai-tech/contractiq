#!/usr/bin/env bash
# Block until the API reports ready (used in CI and deploy smoke tests).
set -euo pipefail
URL="${1:-http://localhost:8000/api/v1/ready}"
for i in $(seq 1 60); do
  if curl -fsS "$URL" >/dev/null; then echo "ready"; exit 0; fi
  sleep 2
done
echo "timed out waiting for $URL" >&2; exit 1
