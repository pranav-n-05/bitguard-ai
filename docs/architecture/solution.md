# Proposed solution

A modular monolith (FastAPI + Celery + PostgreSQL + Redis + React) running a staged pipeline:

`ingest → validate/normalise/dedup → canonical store → features → correlation → graph patterns/clusters → ML → risk → alerts`

Key design decisions
1. **Immutable evidence chain.** Every source record is staged byte-faithfully in `raw_records` (DB trigger blocks UPDATE/DELETE). Canonical rows point back to their raw record; evidence snapshots carry file hash, record hash and analysis versions.
2. **Leakage-safe features.** One time-ordered pass; each row only sees earlier state. A unit test proves future data cannot change past features.
3. **Honest ML.** Unsupervised models; supervised-style metrics only against synthetic injected labels and labelled as such; scores are outlier ranks, not probabilities.
4. **Transparent risk.** Weighted components stored per assessment; unavailable evidence raises uncertainty instead of counting as zero; guards against double counting and size-only alerts.
5. **Defensible workflow.** State machines for alerts and cases, RBAC on every endpoint, hash-chained audit log, reports hashed and verified on download.
