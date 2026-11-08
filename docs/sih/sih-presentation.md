---
marp: true
theme: default
paginate: true
backgroundColor: "#080D18"
color: "#E5E7EB"
style: |
  h1, h2 { color: #F7931A }
  a, strong { color: #38BDF8 }
  table { font-size: 0.7em }
---

# BITGUARD AI
### AI-powered monitoring & analysis of Bitcoin transaction traffic
SIH26146 · NTRO · Smart Automation / Blockchain & Cybersecurity

*Offline · explainable · evidence-backed · every alert is a lead, not a verdict*

---

## The problem
* Pseudonymous, high-volume, multi-input/multi-output transactions
* Analysts need triage, correlation with network metadata, and defensible documentation
* Constraint: **offline bulk data**, no live node, no attribution claims

---

## Our approach
`ingest → validate → store → correlate → features → graph → ML → risk → alerts → cases → reports`

* Immutable evidence chain: file hash → raw record → canonical → feature → score → alert → case
* Facts, features, heuristics, ML outputs and analyst decisions kept separate

---

## Ingestion you can trust
* CSV · JSON · JSONL · XML, streaming, encoding detection
* Real address checksums (Base58Check, Bech32/Bech32m), exact fee balance, **integer satoshis**
* Quarantine with reasons · dedup · resume after crash · no silent loss
* ~1,000 records/s on a laptop

---

## Blockchain ⇄ network correlation
* IP bursts · repeated address↔IP co-occurrence · ASN concentration
* Each indicator: confidence, evidence, and a fixed limitation:
  **co-occurrence, not ownership**

---

## Graph intelligence
* Bipartite Address → Transaction → Address (never collapsed)
* Fan-in/out · peel chains · layering · cycles · shortest path · flow trace
* Probabilistic clusters with confidence, limits and analyst review
* CoinJoin treated as privacy, not crime

---

## Real, honest ML
* Isolation Forest (primary) vs LOF — versioned, hashed, reproducible, time-ordered holdout
* **Synthetic holdout:** IF PR-AUC **0.92**, P@100 **0.98**; LOF 0.37 → IF auto-selected
* Explanations: SHAP / robust deviation per prediction
* ⚠ Optimistic by construction (injected patterns) — stated in the product

---

## Transparent risk (0–100)
* Components, weights and rule version stored; history preserved with reasons
* Guards: no double counting · size alone ≤ Moderate · CoinJoin capped · missing evidence = uncertainty, not zero
* Result on seed 42: 328/328 injected patterns Elevated · 0 baseline above Moderate

---

## Analyst console
Dashboard · Transactions · Address · Graph · AI · Alerts · Investigations · Reports · Ingestion · Admin
Every score links to its explanation; every graph node links to its page.

---

## Investigation & evidence
* Alert workflow with notes, assignment, false-positive feedback
* Cases with append-only **evidence + integrity hashes**, verification, audit timeline
* PDF / CSV / JSON reports, SHA-256 verified on download

---

## Security & integrity
Argon2id · JWT rotation + reuse detection · MFA · RBAC (19 permissions) · rate limits · secure headers
Hash-chained, append-only audit log · DB-enforced immutability of raw data and evidence

---

## Production readiness
* Docker Compose: db · redis · API · Celery worker · nginx gateway, healthchecks
* Backup/restore scripts (tested) · structured logs · CI (lint, types, tests, audits)
* **118 backend tests · 15 UI tests · browser E2E on the container stack**

---

## Limitations (we state them)
Synthetic data · address-level linkage · heuristic clusters · no live node · single-node scale tested
→ docs/known-limitations.md

---

## Thank you
Treat every alert as an **investigative lead**.
