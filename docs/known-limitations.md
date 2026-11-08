# Known limitations

Stated plainly so the system is used responsibly.

## Data and scope
* **Synthetic data only.** All performance figures come from injected synthetic patterns and are optimistic. There is no real labelled data and no live node/stream.
* **No outpoint (prevout) references** in the input schema. Transaction-to-transaction linkage (flow tracing, peel chains, layering, cycles, path analysis) is **address-level** and can over-connect reused addresses or miss links through unseen transactions.
* Coinbase transactions (no inputs) and records with unknown address formats are quarantined. Integer amount strings are read as **satoshis** and decimal strings as BTC — a feed that sends whole BTC as integers would be misread.
* Encoding detection is heuristic; very small non-UTF-8 files can be misdetected. `asn` and `geo_country` are used as supplied (not independently verified); nulls are kept as *unavailable*.

## Analytics
* **Heuristics are not proof.** Common-input, change-output and behavioural clusters are probabilistic aids. CoinJoin-like detection (equal-denomination multi-party) is itself a heuristic; PayJoin and custodial batching can defeat it. Confidence values are uncalibrated.
* **Network correlation shows co-occurrence/timing only.** Relay nodes, VPN/NAT egress and shared hosts produce the same signals; an IP never identifies an address owner.
* Isolation Forest outputs an outlier **rank**, not a probability. Flag thresholds use fixed contamination (0.02), which limits recall by construction. LOF was clearly weaker on this data.
* SHAP explanations are computed for the 300 highest-scoring entities per run; others use a robust-deviation explanation (labelled per prediction).
* Betweenness centrality is sampled (k=400, fixed seed); the cycle search is bounded (length ≤ 6, ≤ 7 days) and may miss longer layering.
* The analytics stage recomputes all derived tables from canonical data on each run (simple and idempotent; not incremental). Single-node processing was measured on ~11k records only.

## Platform
* One Celery worker pool, no priority queues; graph queries are bounded (≤ 2,000 nodes) rather than streamed.
* No TLS termination, SSO/LDAP, password-reset email, or MFA recovery codes (administrators reset MFA/passwords). Refresh tokens live in `sessionStorage`.
* Monitoring is logs + health endpoints; no metrics/alerting stack is shipped. Postgres/Redis ports are published in the dev compose file.
* Frontend: Chromium-tested only; limited component tests; graph rendering uses Cytoscape and is not screen-reader navigable (data is available on the entity pages).
* Reports are generated synchronously; very large exports are capped (20,000 alert rows / 100,000 transactions).

## Not in scope
Private-key storage, wallet signing, broadcasting, deanonymisation, or any automated decision about individuals.
