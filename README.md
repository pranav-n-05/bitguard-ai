# BITGUARD AI

**AI-powered monitoring and analysis of Bitcoin transaction traffic** — SIH26146 (NTRO).
An offline, explainable transaction-and-network-metadata intelligence platform: ingest bulk data, correlate
blockchain and network layers, build an investigable graph, detect anomalies with real ML, score risk
transparently, raise evidence-backed alerts and manage investigations to exported reports.

> **Every output is an investigative lead, never a legal conclusion.** An address is not a person; an IP
> co-occurrence is not ownership; a cluster is not an entity; an anomaly is not proof of crime.
> All bundled data is **synthetic**. The system runs **offline** on bulk files and has **no live node** connection.

## What is implemented

| Area | Implementation |
|---|---|
| Ingestion | CSV / JSON / JSONL / XML streaming parsers, encoding+format detection, checksum integrity, address checksum validation (Base58Check, Bech32/Bech32m), exact fee balance, integer satoshis, quarantine with reasons, dedup, immutable raw staging, resumable checkpoints, dead letters |
| Correlation | IP burst, repeated address↔IP co-occurrence, ASN concentration, non-standard ports — each with confidence, evidence refs and fixed "not attribution" limitation |
| Features | 28 point-in-time (leakage-safe) transaction features, 17 address features, plus per-IP / ASN / country network features; ML-ready, with missing values left unavailable (never zero-filled) |
| Graph | Bipartite Address→Tx→Address model with IP/ASN/Country/Cluster/Case nodes, N-hop expansion, shortest path, flow tracing, fan-in/out, peel chain, layering, cycles, sampled betweenness, common-input / change-output / behavioural clusters |
| ML | Isolation Forest (primary) + Local Outlier Factor, time-ordered split, model versioning with SHA-256 artifacts, SHAP/robust-deviation explanations, honest evaluation (labelled only for synthetic injected patterns) |
| Risk | Transparent 0–100 score, stored components/weights/rule version, double-count and size-only guards, CoinJoin cap, supersession history |
| Alerts | 14 categories, configurable thresholds, dedup, workflow state machine, assignment, notes, analyst feedback |
| Cases | Investigations, linked entities, notes, append-only evidence with provenance + integrity hash and verification |
| Reports | PDF / CSV / JSON, SHA-256 verified on download |
| Security | Argon2id, JWT access+refresh with rotation and reuse detection, lockout, TOTP MFA, RBAC (19 permissions, 4 roles), hash-chained append-only audit log, rate limiting, security headers, body limits |
| UI | React console: dashboard, transactions, tx detail, address, graph, AI, alerts, investigations, reports, ingestion, admin |
| Ops | Docker Compose (db, redis, backend, Celery worker, nginx gateway), healthchecks, backup/restore scripts, GitHub Actions CI |

## Quick start (Docker)

```bash
cp .env.example .env     # set BITGUARD_JWT_SECRET (>=32 random bytes) and BITGUARD_BOOTSTRAP_ADMIN_PASSWORD
docker compose --profile app up -d --build
backend/.venv/bin/python scripts/generate_synthetic.py --seed 42 --formats jsonl   # see docs/deployment for venv setup
scripts/demo.sh          # upload + process synthetic data end to end
open http://localhost:8080
```

**Deploy on Render:** `render.yaml` blueprint, see [docs/deployment/render.md](docs/deployment/render.md).

Development setup, tests, backup/restore, and every other topic: see [docs/](docs/README.md).

## Verification status (measured, not claimed)

* Backend: 118 pytest tests (real PostgreSQL), `ruff` clean, `mypy --strict` clean.
* Frontend: 15 Vitest tests, TypeScript strict build, 1 Playwright end-to-end scenario (upload → alerts → case → evidence → PDF) passing against the Docker stack with a real Celery worker.
* ML metrics are measured on **synthetic injected patterns** and are documented with that caveat in [docs/ml/evaluation.md](docs/ml/evaluation.md).

Known limitations: [docs/known-limitations.md](docs/known-limitations.md).
