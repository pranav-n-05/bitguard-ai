# Analyst user manual

> Every score, alert, cluster and network association is an **investigative lead**. Verify before acting. Data is labelled
> *synthetic* / *historical*; the console works offline on bulk files and is not connected to any live node.

## Sign in
Open the console (default `http://localhost:8080`). Enter email and password (and the 6-digit code if MFA is enabled). Accounts lock for 15 minutes after 5 failed attempts.
Enable MFA and change your password under **Administration → My security**.

## Navigation
Sidebar: Dashboard · Transactions · Addresses · Graph intelligence · AI intelligence · Alerts · Investigations · Reports · Data ingestion · Administration.
The top search accepts a txid, an address or an IP and jumps to the right page. Items you may not use are hidden or show "Not permitted".

## Typical workflow
1. **Ingest** (Data ingestion): upload CSV/JSON/JSONL/XML, choose provenance, *Upload & process*. Watch the job; open **Errors** to see quarantined records and reasons.
2. **Dashboard:** data window, record quality, volume, risk and anomaly distributions, highest-risk open alerts, priority cases, recent audit activity. Missing data is shown as *unavailable*, never as zero.
3. **Alerts:** filter by status, severity, category, assignment. Open an alert to read *what happened*, *why it was flagged* (triggered rules with thresholds and observed values), *evidence* (transaction, addresses, observations) and *what remains uncertain*.
   Workflow: New → Acknowledged → Under investigation → Escalated → Resolved / False positive. Resolve and false-positive require a note; false-positive feeds the analyst-feedback label set. Analysts acknowledge and investigate; escalation/resolution needs senior analyst or administrator.
4. **Transactions / Transaction detail:** inputs and outputs, features, network observations (co-occurrence only), structural detections, **Graph** and **Risk & explanation** tabs. Click any risk score to open its components, model explanation, history and related alerts.
5. **Address page:** activity, graph, risk indicators, probabilistic clusters (never entities), investigations. A balance shown is an estimate from ingested data only.
6. **Graph intelligence:** expand around a txid/address (1-4 hops), toggle context nodes, export PNG/JSON, find the shortest path between two addresses, browse structural detections and clusters. Click a node, then **Open** to go to its page. Clusters can be marked plausible/rejected (audited).
7. **Investigations:** *Add to case* from any alert, transaction or address, or create a case. In a case: link entities, attach **evidence** (snapshot + provenance + integrity hash), add notes, **Verify** evidence integrity, review the audit timeline, export PDF/CSV/JSON. Closing a case needs an analyst decision.
8. **AI intelligence:** compare model versions and evaluation (with caveats), feature importance among outliers, prediction explanations. Senior analysts can retrain and activate versions.
9. **Reports:** generate alert or transaction registers; every report shows its SHA-256 and is verified on download.
10. **Administration** (admins): users and roles, permission matrix, risk weights and alert thresholds (versioned, audited, apply after **Recompute pipeline**), audit log with chain verification.

## Reading a risk score
0-24 Low, 25-49 Moderate, 50-74 Elevated, 75-100 High — prioritisation bands, **not** probabilities. Check *Uncertainty* and *Limitations*; CoinJoin-like structures are capped and explained; a large amount alone never reaches Elevated.

## Good practice
Corroborate with independent sources; record reasoning in notes and the analyst decision; do not treat an IP, cluster or anomaly as identification; export a report rather than copying screenshots so provenance travels with the finding.
