#!/bin/bash
# Runs migrations + seed, then the Celery worker (background) and the API (foreground-ish).
# If either process exits the container exits, so Render restarts it.
set -euo pipefail
cd /app
alembic upgrade head
python -m app.bootstrap
celery -A app.workers.celery_app worker --loglevel=INFO --concurrency="${CELERY_CONCURRENCY:-2}" &
uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1 &
wait -n
exit $?
