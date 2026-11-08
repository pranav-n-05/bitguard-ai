# Model evaluation report

> **Read first.** These numbers are measured on a **synthetic** dataset in which the suspicious patterns were injected by our own
> generator (`backend/app/ingestion/synthetic.py`, seed 42). Injected structures are deliberately distinct, so the metrics are **optimistic**
> and are **not an estimate of real-world performance**. No real labelled data was available. Nothing here is a claim about criminal activity.

## Setup
* Dataset: seed 42, 6,340 unique valid transactions, 7,751 addresses; 30% time-ordered holdout (1,902 transactions, 127 injected-suspicious = 6.7% base rate; 2,326 addresses, 632 positive).
* Labels (`evaluation_labels`, source `synthetic_injected`) are imported only for evaluation and never used as features. CoinJoin-like and large-but-normal transactions are labelled **benign** to test that the system does not flag privacy structures or size alone.
* Flag threshold: model contamination 0.02 (so recall is intentionally limited; ranking metrics are more informative).

## Results (holdout, seed 42)
| Model | Entity | PR-AUC | ROC-AUC | Precision | Recall | FPR | P@50 | P@100 | Seed stability (Spearman) |
|---|---|---|---|---|---|---|---|---|---|
| **Isolation Forest** (active) | transaction | **0.916** | 0.996 | 0.954 | 0.323 | 0.0011 | 0.96 | 0.98 | 0.982 |
| Local Outlier Factor | transaction | 0.375 | 0.662 | 0.560 | 0.331 | 0.0186 | 0.62 | 0.47 | 1.000 (deterministic) |
| **Isolation Forest** (active) | address | **0.907** | 0.959 | 1.000 | 0.427 | 0.000 | 1.00 | 1.00 | 0.993 |
| Local Outlier Factor | address | 0.760 | 0.786 | 0.883 | 0.511 | 0.0254 | 1.00 | 0.98 | 1.000 |
The best algorithm per entity type by holdout PR-AUC is activated automatically; the other version is retained for comparison.

## Downstream behaviour (same run)
* **Risk bands:** all 328 transactions in injected suspicious patterns scored **Elevated**; **no** baseline transaction exceeded **Moderate** (673 Moderate, 5,327 Low); CoinJoin-like controls Low/Moderate; large-but-normal controls Moderate.
* **Alerts:** 130 alerts generated; every one concerned an injected suspicious entity (no alert on baseline or benign controls). One rule that over-fired on single-transaction addresses (573 alerts) was tightened and addresses already covered by a transaction/network alert are no longer re-alerted.
* **Structural detectors:** 30/30 injected fan-out, fan-in, peel-chain, cycle and layering instances found, with zero detections on benign controls.

## Why the numbers are optimistic
Injected patterns (e.g. 25-50 near-equal outputs, bursts of 25-40 transactions from one IP) are far more extreme than most real behaviour; the baseline is simple and homogeneous; the same author defined patterns, features and detectors.
Expect materially lower precision and recall on real data, where legitimate exchanges, payroll and mixers produce the same structures.

## What is not evaluated
No labelled real data; no calibration of the anomaly score or heuristic confidences; no analyst-feedback evaluation beyond the mechanism (feedback labels are stored); no drift study.
When analyst feedback accumulates, `model_evaluations` will record metrics with source `analyst_feedback`; precision at top-K of alerts and false-positive rate of the alert queue are the recommended operational metrics.

## Reproduce
```bash
backend/.venv/bin/python scripts/generate_synthetic.py --seed 42 --formats jsonl
# upload (UI or scripts/demo.sh), import labels file (AI page or POST /ai/labels/import), train (POST /ai/models/train)
```
