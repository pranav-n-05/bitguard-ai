# Software requirements specification (as implemented)

## Functional requirements
| ID | Requirement | Verified by |
|---|---|---|
| FR-1 | Ingest CSV, JSON, JSONL, XML offline; detect format/encoding; verify file checksum | `tests/test_ingestion.py`, `tests/test_parsers.py` |
| FR-2 | Validate fields, normalise timestamps to UTC, convert BTC to integer satoshis, reject sub-satoshi | `tests/test_normalize.py` |
| FR-3 | Quarantine invalid records with reasons; deduplicate by content hash; resume after interruption | `tests/test_ingestion.py` |
| FR-4 | Correlate network observations with transactions and addresses with confidence and limitations | `tests/test_analytics.py` |
| FR-5 | Build features (transaction, address, network) without temporal leakage | `test_features_are_leakage_free` |
| FR-6 | Bipartite entity-transaction graph; N-hop, path, trace, patterns, clusters | `tests/test_analytics.py` |
| FR-7 | Train/version/compare anomaly models; explain predictions | `tests/test_ml_risk_alerts.py` |
| FR-8 | Transparent 0-100 risk with stored components, weights, rule version and history | `tests/test_ml_risk_alerts.py` |
| FR-9 | Alerts from detection results, with workflow, dedup, assignment, notes | `tests/test_ml_risk_alerts.py` |
| FR-10 | Investigations with notes, linked entities, append-only evidence, verification | `tests/test_cases_security.py` |
| FR-11 | PDF/CSV/JSON reports, hash-verified | `tests/test_cases_security.py` |
| FR-12 | RBAC, audit chain, MFA, rate limiting, secure headers | `tests/test_cases_security.py`, `tests/test_auth.py` |
| FR-13 | Web console for all workflows | Vitest + Playwright |

## Non-functional requirements
* **Offline:** no outbound network calls at runtime (no CDN fonts/maps/QR services).
* **Integrity:** raw records, audit log and evidence are append-only at the database level.
* **Reproducibility:** fixed seeds; model artifact SHA-256 verified before load.
* **Security:** see [security.md](../security/security.md).
* **Performance (measured, dev laptop):** ingestion ~1,000 records/s; full analytics+ML+risk+alerts pipeline on 6.3k transactions in about one minute.
* **Operability:** JSON structured logs with request/correlation IDs; health endpoint; Compose healthchecks; backup/restore scripts.

## Data requirements
Minimum fields per record: `timestamp, src_ip, dst_ip, src_port, dst_port, txid, input_addresses, output_addresses,
input_amounts, output_amounts, fee, script_type, geo_country, asn`. Optional: block height/hash, confirmations, version,
locktime, size, vsize, weight, protocol, extra metadata (kept in `network_observations.extra`).
`geo_country` and `asn` may be null (stored as unavailable, never as zero).
