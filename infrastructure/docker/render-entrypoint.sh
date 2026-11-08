#!/bin/bash
set -euo pipefail
mkdir -p "${BITGUARD_STORAGE_DIR:-/data/storage}" "${BITGUARD_MODEL_DIR:-/data/models}"
chown -R bitguard:bitguard /data
exec runuser -u bitguard -- /app/render-run.sh
