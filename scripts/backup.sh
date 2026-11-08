#!/usr/bin/env bash
# Backup PostgreSQL + stored files (uploads, reports, model artifacts) into ./backups/<timestamp>/
# Usage: scripts/backup.sh [output_dir]
set -euo pipefail
cd "$(dirname "$0")/.."
OUT="${1:-backups}/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$OUT"
docker compose exec -T db pg_dump -U "${POSTGRES_USER:-bitguard}" -Fc "${POSTGRES_DB:-bitguard}" > "$OUT/db.dump"
docker compose --profile app run --rm --no-deps -T -v "$(cd "$OUT" && pwd):/backup" --entrypoint tar backend czf /backup/files.tgz -C /data storage models
( cd "$OUT" && shasum -a 256 db.dump files.tgz > SHA256SUMS )
echo "Backup written to $OUT"; cat "$OUT/SHA256SUMS"
