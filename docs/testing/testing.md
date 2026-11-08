# Testing

All fixtures are **synthetic** and deterministic (seeded generator).

| Layer | Tool | Count | Notes |
|---|---|---|---|
| Backend unit + integration | pytest + real PostgreSQL | 118 | migrations applied fresh (down → up) per run; async tests share one event loop |
| Static analysis | ruff, mypy `--strict` | — | 0 findings |
| Frontend unit | Vitest + Testing Library | 15 | formatting, state components, login validation, API helpers |
| Frontend types/build | tsc strict, Vite | — | |
| End-to-end | Playwright (Chromium) | 1 | spec §18 scenario against the Docker stack with a real Celery worker |

## Running
```bash
docker compose --profile test up -d db-test redis
cd backend && .venv/bin/pytest -q && .venv/bin/ruff check app tests ../scripts && .venv/bin/mypy app
cd frontend && npm test && npm run lint && npm run build
# E2E (stack running on :8080, credentials of an administrator)
BITGUARD_E2E_URL=http://localhost:8080 BITGUARD_E2E_PASSWORD=... npx playwright test
```
CI (`.github/workflows/ci.yml`) runs backend (with Postgres and Redis services), frontend, `pip-audit`, `npm audit` and a Compose build.

## What the suites prove
* **Ingestion:** all four formats produce identical canonical records; quarantine reasons recorded; duplicates create no entities; resume after a simulated crash has no gaps/duplicates; tampered files are rejected; append-only triggers fire; XXE not resolved; unsafe extensions rejected.
* **Money:** integer satoshis, exact BTC conversion (`0.1 + 0.2 = 0.3`), sub-satoshi rejection.
* **Intelligence:** point-in-time features are unchanged by future data; injected patterns are recovered and benign controls are not flagged; CoinJoin excluded from clustering; model fits are reproducible; size alone cannot reach Elevated; unavailable evidence raises uncertainty; recalculation supersedes with a reason; alert dedup and illegal state transitions.
* **Security:** RBAC matrix, lockout, refresh rotation and reuse detection, MFA, rate limit (429), headers, 413 body limit, sanitised errors, audit-chain verification, evidence and report tamper detection.
* **Dependencies:** running the real containerised stack exposed that `redis-py` 5.x was incompatible with the installed kombu — a defect invisible in eager test mode (dispatch returned HTTP 500). Fixed by pinning celery 5.7.0 / redis 6.4.0; `tests/test_broker.py` now guards against regression.

## Not covered
Load/soak testing beyond the 11k-row dataset; browser matrix beyond Chromium; accessibility audit beyond semantic roles/labels; chaos/failover tests; per-page frontend component tests for every page (smoke-covered by the E2E scenario).
