# REST API reference

Generated from the OpenAPI schema by `scripts/gen_docs.py` (live schema at `/api/v1/openapi.json`, interactive docs at `/api/docs` when enabled).

* Base path: `/api/v1`. Auth: `Authorization: Bearer <access token>` (except `/health` and `/auth/login|refresh`).
* Errors: RFC 9457 `application/problem+json` with `request_id`; internals are never leaked.
* Lists: `limit` (1-500), `offset`, `sort` (`field` or `-field`, allow-listed per endpoint) and endpoint-specific filters; responses are `{items,total,limit,offset}`.
* Rate limits: login 10/min/IP, default 600/min/IP (configurable). Request bodies: JSON 1 MiB, uploads 512 MiB.

## addresses

| Method | Path | Summary |
|---|---|---|
| POST | `/api/v1/api/v1/addresses/analyze` | On-demand analysis for up to 50 addresses |
| GET | `/api/v1/api/v1/addresses/{address}` | Get Address |
| GET | `/api/v1/api/v1/addresses/{address}/graph` | Address Graph |
| GET | `/api/v1/api/v1/addresses/{address}/risk` | Address Risk |
| GET | `/api/v1/api/v1/addresses/{address}/statistics` | Address Statistics |
| GET | `/api/v1/api/v1/addresses/{address}/transactions` | Address Transactions |

## administration

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/api/v1/admin/audit-logs` | Audit Logs |
| GET | `/api/v1/api/v1/admin/audit-logs/verify` | Verify the audit hash chain end to end |
| GET | `/api/v1/api/v1/admin/configuration` | Get Config |
| PATCH | `/api/v1/api/v1/admin/configuration` | Patch Config |
| POST | `/api/v1/api/v1/admin/pipeline/rerun` | Recompute analytics, risk and alerts with current configuration |
| GET | `/api/v1/api/v1/admin/roles` | Roles |
| GET | `/api/v1/api/v1/admin/users` | List Users |
| POST | `/api/v1/api/v1/admin/users` | Create User |
| GET | `/api/v1/api/v1/admin/users/assignable` | Assignable |
| PATCH | `/api/v1/api/v1/admin/users/{user_id}` | Patch User |

## ai

| Method | Path | Summary |
|---|---|---|
| POST | `/api/v1/api/v1/ai/analyze/address` | Ai Analyze Addr |
| POST | `/api/v1/api/v1/ai/analyze/transaction` | Ai Analyze Tx |
| POST | `/api/v1/api/v1/ai/labels/import` | Import SYNTHETIC generator labels for evaluation only |
| GET | `/api/v1/api/v1/ai/models` | List Models |
| GET | `/api/v1/api/v1/ai/models/evaluation` | Evaluations |
| POST | `/api/v1/api/v1/ai/models/train` | Train |
| GET | `/api/v1/api/v1/ai/models/{model_id}` | Get Model |
| POST | `/api/v1/api/v1/ai/models/{model_id}/activate` | Activate |
| GET | `/api/v1/api/v1/ai/predictions` | Predictions |

## alerts

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/api/v1/alerts` | List Alerts |
| POST | `/api/v1/api/v1/alerts` | Create a manual analyst alert |
| GET | `/api/v1/api/v1/alerts/{alert_id}` | Get Alert |
| PATCH | `/api/v1/api/v1/alerts/{alert_id}` | Patch Alert |
| POST | `/api/v1/api/v1/alerts/{alert_id}/acknowledge` | Acknowledge |
| POST | `/api/v1/api/v1/alerts/{alert_id}/resolve` | Resolve |

## analytics

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/api/v1/analytics/anomalies` | Anomalies |
| GET | `/api/v1/api/v1/analytics/network-patterns` | Network Patterns |
| GET | `/api/v1/api/v1/analytics/overview` | Overview |
| GET | `/api/v1/api/v1/analytics/risk-distribution` | Risk Distribution |
| GET | `/api/v1/api/v1/analytics/transaction-volume` | Transaction Volume |

## auth

| Method | Path | Summary |
|---|---|---|
| POST | `/api/v1/api/v1/auth/login` | Authenticate and obtain access/refresh tokens |
| POST | `/api/v1/api/v1/auth/logout` | Revoke a refresh token |
| GET | `/api/v1/api/v1/auth/me` | Me |
| POST | `/api/v1/api/v1/auth/mfa/disable` | Mfa Disable |
| POST | `/api/v1/api/v1/auth/mfa/enable` | Mfa Enable |
| POST | `/api/v1/api/v1/auth/mfa/setup` | Generate a TOTP secret (MFA stays disabled until confirmed) |
| POST | `/api/v1/api/v1/auth/password` | Change Password |
| POST | `/api/v1/api/v1/auth/refresh` | Rotate refresh token |

## graph

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/api/v1/graph/clusters` | Clusters |
| GET | `/api/v1/api/v1/graph/clusters/{cluster_id}` | Cluster |
| PATCH | `/api/v1/api/v1/graph/clusters/{cluster_id}` | Record analyst review of a cluster |
| GET | `/api/v1/api/v1/graph/detections` | Detections |
| GET | `/api/v1/api/v1/graph/path` | Shortest path between two addresses over the bipartite graph |

## ingestion

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/api/v1/ingestion/datasets` | List Datasets |
| POST | `/api/v1/api/v1/ingestion/datasets` | Register a dataset and upload file(s) |
| GET | `/api/v1/api/v1/ingestion/datasets/{dataset_id}` | Get Dataset |
| POST | `/api/v1/api/v1/ingestion/datasets/{dataset_id}/process` | Start or resume processing (resumes from last checkpoint) |
| GET | `/api/v1/api/v1/ingestion/errors` | List Errors |
| GET | `/api/v1/api/v1/ingestion/jobs` | List Jobs |
| GET | `/api/v1/api/v1/ingestion/jobs/{job_id}` | Get Job |

## investigations

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/api/v1/investigations` | List Cases |
| POST | `/api/v1/api/v1/investigations` | Create Case |
| GET | `/api/v1/api/v1/investigations/{case_id}` | Get Case |
| PATCH | `/api/v1/api/v1/investigations/{case_id}` | Patch Case |
| POST | `/api/v1/api/v1/investigations/{case_id}/entities` | Link transactions, addresses, alerts or network observations |
| GET | `/api/v1/api/v1/investigations/{case_id}/evidence` | List Evidence |
| POST | `/api/v1/api/v1/investigations/{case_id}/evidence` | Attach Evidence |
| GET | `/api/v1/api/v1/investigations/{case_id}/evidence/{evidence_id}/verify` | Recompute integrity and provenance hashes |
| POST | `/api/v1/api/v1/investigations/{case_id}/export` | Export Case |
| POST | `/api/v1/api/v1/investigations/{case_id}/notes` | Add Note |

## network

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/api/v1/network/asns/{asn}` | Get Asn |
| GET | `/api/v1/api/v1/network/correlations` | Correlations |
| GET | `/api/v1/api/v1/network/ips/{ip}` | Get Ip |
| GET | `/api/v1/api/v1/network/patterns` | Aggregate network patterns: ports, protocols, countries, top origin IPs |

## reports

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/api/v1/reports` | List Reports |
| POST | `/api/v1/api/v1/reports/generate` | Generate |
| GET | `/api/v1/api/v1/reports/{report_id}` | Get Report |
| GET | `/api/v1/api/v1/reports/{report_id}/download` | Download |

## system

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/api/v1/health` | Liveness/readiness probe (no auth) |
| GET | `/api/v1/api/v1/system/metrics` | Metrics |
| GET | `/api/v1/api/v1/system/status` | Status |

## transactions

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/api/v1/transactions` | Search transactions |
| POST | `/api/v1/api/v1/transactions/analyze` | On-demand analysis (features, reproducible model score, risk explanation) for up to 50 txids |
| GET | `/api/v1/api/v1/transactions/{txid}` | Get Transaction |
| GET | `/api/v1/api/v1/transactions/{txid}/graph` | Cytoscape elements around a transaction |
| GET | `/api/v1/api/v1/transactions/{txid}/inputs` | Get Inputs |
| GET | `/api/v1/api/v1/transactions/{txid}/outputs` | Get Outputs |
| GET | `/api/v1/api/v1/transactions/{txid}/risk` | Current risk assessment with components, explanation and history |
| GET | `/api/v1/api/v1/transactions/{txid}/trace` | Follow value forward/backward (address-level) |
