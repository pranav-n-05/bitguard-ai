# Installation, deployment and operations

## Requirements
Linux or macOS with Docker (Compose v2). For development: Python 3.12+ (tested on 3.13) with `uv`, Node 22. No internet is needed at runtime.

## Production-style deployment (Docker Compose)
```bash
cp .env.example .env
# edit .env: BITGUARD_JWT_SECRET (>=32 random bytes, e.g. openssl rand -hex 32),
#            BITGUARD_BOOTSTRAP_ADMIN_EMAIL / BITGUARD_BOOTSTRAP_ADMIN_PASSWORD, POSTGRES_PASSWORD, BITGUARD_ENV=production
docker compose --profile app up -d --build
curl localhost:8080/api/v1/health        # {"status":"ok","database":true,"redis":true}
```
Services: `db` (PostgreSQL 16), `redis`, `backend` (FastAPI; runs Alembic migrations and bootstraps roles/admin on start), `worker` (Celery),
`api-gateway` (nginx serving the SPA and proxying `/api/` on **:8080**). Named volumes: `pgdata`, `redisdata`, `storage` (uploads/reports), `models` (artifacts).
Healthchecks: db (`pg_isready`), redis, backend (`/api/v1/health`), gateway (`/healthz`). `db-test` exists only under the `test` profile.

Put TLS termination (reverse proxy / load balancer) in front of port 8080; do not expose 5432/6379 outside the host (remove their `ports:` in production).

## Development setup
```bash
docker compose --profile test up -d db db-test redis
cd backend && uv venv --python 3.13 .venv && uv pip install -r requirements-dev.txt
.venv/bin/alembic upgrade head && .venv/bin/python -m app.bootstrap
.venv/bin/uvicorn app.main:app --reload            # API on :8000 (docs: /api/docs)
cd ../frontend && npm ci && npm run dev            # UI on :5173 (proxies /api to :8000)
```

## Configuration (environment)
| Variable | Purpose |
|---|---|
| `BITGUARD_DATABASE_URL`, `BITGUARD_REDIS_URL` | connections |
| `BITGUARD_JWT_SECRET` | signing secret (required in production) |
| `BITGUARD_ACCESS_TOKEN_MINUTES`, `BITGUARD_REFRESH_TOKEN_DAYS` | token lifetimes |
| `BITGUARD_CORS_ORIGINS` | comma-separated or JSON list |
| `BITGUARD_MAX_UPLOAD_MB`, `BITGUARD_STORAGE_DIR`, `BITGUARD_MODEL_DIR` | limits and paths |
| `BITGUARD_LOGIN_RATE_LIMIT`, `BITGUARD_DEFAULT_RATE_LIMIT` | slowapi limits |
| `BITGUARD_CELERY_EAGER` | run pipeline inline (tests/single process) |

## Synthetic data and demo
```bash
backend/.venv/bin/python scripts/generate_synthetic.py --seed 42 --formats jsonl,csv,json,xml
scripts/demo.sh        # upload + process + import labels + train + recompute; prints overview
```
Offline CLI ingestion without HTTP: `cd backend && .venv/bin/python ../scripts/ingest_local.py --name seed42 ../ml/datasets/synthetic/bitguard_synthetic_seed42.jsonl`.

## Backup and restore
```bash
scripts/backup.sh                       # backups/<UTC timestamp>/{db.dump,files.tgz,SHA256SUMS}
scripts/restore.sh backups/<timestamp> --yes   # verifies checksums, replaces DB + files, restarts the stack
```
Both scripts were exercised against the running stack: checksums verified, transaction count identical before/after, login works afterwards.
After a restore, run Admin → Audit log → **Verify chain**.

## Monitoring and logs
Structured JSON logs (`request_id`, `correlation_id`, level, UTC timestamp) on stdout for `backend` and `worker`: `docker compose logs -f backend worker`.
Liveness/readiness: `GET /api/v1/health`. Pipeline progress: Data ingestion page / `GET /ingestion/jobs`. Audit trail: `GET /admin/audit-logs`.
`infrastructure/monitoring/` is reserved; no Prometheus/Grafana stack is shipped (see known limitations).

## Upgrades and migrations
`alembic upgrade head` runs automatically at backend start. Back up before upgrading. Migrations are tested up → down → up in CI via the test fixtures.
