# System architecture

Modular monolith with clear package boundaries so modules can be extracted later.

```mermaid
flowchart LR
  UI[React console<br/>nginx :8080] -->|/api/v1| API[FastAPI]
  API --> PG[(PostgreSQL)]
  API --> RD[(Redis)]
  API -->|enqueue| W[Celery worker]
  W --> PG
  W --> ML[(Model artifacts<br/>joblib + sha256)]
  W --> FS[(Storage: uploads, reports)]
  API --> FS
```

## Package map (`backend/app`)
`api/v1` routers → `services` → models; `ingestion` (parsers, normaliser, address codec, resumable service, synthetic generator);
`analytics` (loader, point-in-time features); `intelligence` (network correlation); `graph` (patterns, clustering, DB-backed queries);
`ml` (engine); `alerts` (rules, engine, workflow); `investigations`; `reports`; `workers` (Celery); `core` (config, security, RBAC, errors, hashing, middleware).

## Data flow
```mermaid
flowchart TD
  F[Dataset file] -->|sha256, format, encoding| S[Immutable raw_records]
  S --> V{Validate + normalise}
  V -->|invalid| Q[ingestion_errors / quarantine]
  V -->|valid or partial| C[transactions, inputs, outputs, addresses, network_observations]
  C --> FE[Features: transaction, address, network]
  C --> CO[Correlation indicators]
  C --> GR[Graph detections + clusters]
  FE --> ML[Isolation Forest + LOF]
  ML --> RK[Risk assessments + components]
  GR --> RK
  CO --> RK
  RK --> AL[Alerts]
  AL --> INV[Investigations, evidence, reports]
```

Layers are never mixed in storage: **observed facts** (canonical tables), **derived features**, **heuristic indicators**
(`graph_detections`, `correlation_indicators`, `address_clusters`), **ML outputs** (`anomaly_predictions`) and **analyst decisions**
(alert/case status, notes, cluster review, evidence).

## Pipeline execution
`POST /ingestion/datasets/{id}/process` creates one job per file and enqueues a Celery task (`BITGUARD_CELERY_EAGER=true` runs inline for tests).
The task ingests in batches (checkpoint committed in the same DB transaction as the batch), then runs stages
`analytics → ml → risk → alerts`. All stages are idempotent and recompute derived tables from canonical data.

## Use cases
```mermaid
flowchart LR
  V((Viewer)) --- U1[Browse transactions, addresses, graph, models]
  A((Analyst)) --- U1
  A --- U2[Acknowledge / investigate alerts]
  A --- U3[Open case, attach evidence, export report]
  S((Senior analyst)) --- U4[Resolve / escalate / false-positive]
  S --- U5[Train models, process datasets, assign cases]
  AD((Administrator)) --- U6[Manage users, thresholds, weights, audit]
```
Roles inherit upwards (viewer ⊂ analyst ⊂ senior analyst ⊂ administrator); the explicit permission matrix is in [security.md](../security/security.md).
