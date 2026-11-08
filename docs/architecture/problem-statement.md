# Problem statement analysis — SIH26146

**Sponsor:** National Technical Research Organisation (NTRO). **Theme:** Smart Automation / Blockchain & Cybersecurity.

## The problem
Bitcoin transaction traffic is pseudonymous, high-volume and structurally complex (multi-input, multi-output).
Analysts need to triage large volumes of transaction and network metadata, find unusual behaviour, correlate
blockchain activity with network observations, and document findings defensibly.

## Interpretation and scope
| Need | Interpretation | Where addressed |
|---|---|---|
| Monitor / analyse traffic | Offline bulk analysis of transaction + network metadata | Ingestion, analytics |
| Detect suspicious patterns | Unsupervised anomaly detection + graph heuristics, never a verdict | ML, graph, alerts |
| Correlate layers | IP / ASN / port / timing ↔ txid ↔ addresses | Correlation engine |
| Support investigation | Cases, evidence with provenance, audit, reports | Investigations, reports |
| Offline Linux | Docker Compose, no external calls | Deployment |

## Hard constraints respected
* Synthetic dataset modelled on real fields; **no live node, no real seized data**.
* Satoshis as integers; no floating-point money.
* Raw facts, derived features, heuristics, ML outputs and analyst decisions are kept separate (data model and UI).
* No claim that an IP owns an address; no claim that common-input / change heuristics prove ownership;
  CoinJoin-like structures are treated as privacy patterns and capped in risk.

## Out of scope (by design)
Private-key handling, signing, broadcasting, live blockchain streaming, deanonymisation claims.
