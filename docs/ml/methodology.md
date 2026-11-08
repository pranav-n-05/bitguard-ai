# AI / ML methodology

## Problem framing
There are no reliable real-world labels. The primary approach is **unsupervised outlier detection** on behavioural and structural
features; its output is a prioritisation signal, **not** a probability of criminality.

## Features (`backend/app/analytics/features.py`)
* **Transaction (28):** value totals, fee and fee rate, in/out counts, imbalance, output-value CV, equal/repeated outputs, round-value ratio,
  fan-in/out, time since previous related transaction, minimum input holding time, chain depth, unique counterparties, address-reuse and
  fresh-input ratios, degree, network observation count, IP/ASN diversity, source-IP 10-minute burst counts/score, unique addresses per IP, CoinJoin-like flag.
* **Address (17) and network-entity features:** address activity, interval, degree and IP/ASN diversity; per IP / ASN / country transaction counts, 10-minute burst maxima, port, ASN and country diversity. The `network_features` table is investigative context; the two models consume only the transaction and address feature sets.
* **Leakage control:** features for a transaction are computed in one time-ordered pass using only earlier state; the network window is
  limited to 60 s after first sighting. Regression test: `test_features_are_leakage_free`.
* **Missing data:** missing values are stored as `null` and imputed in the model pipeline (median imputation plus explicit missing-indicator columns); they are never zero-filled.

## Models (`backend/app/ml/engine.py`, `backend/app/services/ml.py`)
* **Isolation Forest** (primary; 300 trees, contamination 0.02, fixed seed) and **Local Outlier Factor** (novelty, k=35) for comparison.
* Preprocessing: median impute + indicators, RobustScaler (10-90 quantile range); magnitude features are `log1p`-scaled.
* **Split:** time-ordered 70% train / 30% holdout (no shuffling).
* **Versioning:** each training writes a joblib artifact, records SHA-256, parameters, feature schema, training snapshot (row counts + feature hash),
  seed, timestamp and evaluation. The artifact hash is verified before loading. The best algorithm (by holdout PR-AUC when labels exist, otherwise seed stability) is activated automatically.
* **Anomaly score:** percentile of the raw model score within the *training reference distribution* (0-1). It is stable for single-row scoring, but it is a rank, not a probability.

## Explainability
Top contributing features per prediction: SHAP `TreeExplainer` for the 300 highest-scoring entities per run (Isolation Forest), otherwise robust deviation
(|scaled value| in IQR units from the training median). Each explanation lists feature, observed value, direction and whether the value was missing.

## Risk scoring (`backend/app/services/risk.py`)
`score = 100 · Σ w_i n_i / Σ w_i` over **available** components (anomaly 0.30, graph 0.25, network 0.15, velocity 0.10, behavioural deviation 0.10,
history 0.10 — configurable, versioned). Safeguards: anomaly+graph are combined as `max + 0.5·min` to avoid double counting the same structure;
value-only anomalies without structural evidence are capped below Elevated; CoinJoin-like transactions are halved and capped at Moderate; partial
data and unavailable evidence raise **uncertainty**; alert history excludes false positives and the entity's own alerts. Every recalculation creates a new
assessment that supersedes the old with a stored reason.

## Graph heuristics
Peel chains, rapid layering, temporal cycles, fan-in/out and clusters use **address-level linkage** because the data carries no outpoint references.
Common-input clustering excludes CoinJoin-like transactions; change-output links need a clear winner among type-match, non-round value and fresh address.
Confidence values are heuristic, not calibrated probabilities.

## Feedback loop
Marking an alert false positive (or resolving with a confirmation) writes an `analyst_feedback` label used for evaluation only; it is never fed back as a training feature.
