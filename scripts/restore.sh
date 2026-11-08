#!/usr/bin/env bash
# Restore a backup made by scripts/backup.sh. DESTRUCTIVE: replaces the current database and files.
# Usage: scripts/restore.sh backups/<timestamp> --yes
set -euo pipefail
cd "$(dirname "$0")/.."
DIR="${1:?backup directory required}"; [ "${2:-}" = "--yes" ] || { echo "Refusing without --yes (this replaces all data)"; exit 1; }
( cd "$DIR" && shasum -a 256 -c SHA256SUMS )
docker compose --profile app stop backend worker api-gateway
docker compose exec -T db dropdb --force -U "${POSTGRES_USER:-bitguard}" --if-exists "${POSTGRES_DB:-bitguard}"
docker compose exec -T db createdb -U "${POSTGRES_USER:-bitguard}" "${POSTGRES_DB:-bitguard}"
docker compose exec -T db pg_restore -U "${POSTGRES_USER:-bitguard}" -d "${POSTGRES_DB:-bitguard}" --no-owner < "$DIR/db.dump"
docker compose --profile app run --rm --no-deps -T -v "$(cd "$DIR" && pwd):/backup" --entrypoint tar backend xzf /backup/files.tgz -C /data
docker compose --profile app up -d
echo "Restore complete. Verify with: curl localhost:8080/api/v1/health and Admin > Audit log > Verify chain"
