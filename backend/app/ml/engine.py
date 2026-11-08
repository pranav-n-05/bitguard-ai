"""Unsupervised anomaly detection: Isolation Forest (primary) and Local Outlier Factor (comparison).

- Features come from the point-in-time feature store; missing values are median-imputed and get explicit
  missing-indicator columns.
- Time-ordered split: models are fit on the earliest TRAIN_FRACTION of rows and evaluated on the rest.
- Raw model scores are converted to a rank-normalised anomaly score in [0, 1]. This is an outlier rank,
  NOT a probability of wrongdoing.
- Every run is reproducible from (feature rows, schema, params, seed).
"""

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from numpy.typing import NDArray
from scipy.stats import rankdata, spearmanr
from sklearn.ensemble import IsolationForest
from sklearn.impute import SimpleImputer
from sklearn.metrics import average_precision_score, confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score
from sklearn.neighbors import LocalOutlierFactor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import RobustScaler

from app.analytics.features import LOG_FEATURES, TX_FEATURES

TRAIN_FRACTION = 0.7
ADDR_FEATURES = [
    "tx_count",
    "incoming_tx_count",
    "outgoing_tx_count",
    "total_received_sat",
    "total_spent_sat",
    "avg_tx_value_sat",
    "max_tx_value_sat",
    "unique_counterparties",
    "tx_per_day",
    "avg_interval_secs",
    "graph_in_degree",
    "graph_out_degree",
    "ip_diversity",
    "asn_diversity",
    "max_chain_depth",
    "component_size",
    "betweenness",
]
ADDR_LOG = {
    "total_received_sat",
    "total_spent_sat",
    "avg_tx_value_sat",
    "max_tx_value_sat",
    "avg_interval_secs",
    "component_size",
}
FEATURE_SETS: dict[str, tuple[list[str], set[str]]] = {
    "transaction": (TX_FEATURES, LOG_FEATURES),
    "address": (ADDR_FEATURES, ADDR_LOG),
}
VALUE_FEATURES = {
    "total_input_sat",
    "total_output_sat",
    "fee_sat",
    "max_tx_value_sat",
    "total_received_sat",
    "total_spent_sat",
    "avg_tx_value_sat",
    "vsize",
    "fee_rate",
}


def matrix(rows: list[dict[str, Any]], entity_type: str) -> NDArray[Any]:
    names, logs = FEATURE_SETS[entity_type]
    out = np.empty((len(rows), len(names)), dtype=float)
    for i, f in enumerate(rows):
        for j, k in enumerate(names):
            v = f.get(k)
            if v is None or (isinstance(v, float) and math.isnan(v)):
                out[i, j] = np.nan
            else:
                x = float(v)
                out[i, j] = math.log1p(max(x, 0.0)) if k in logs else x
    return out


def preprocessor() -> Pipeline:
    return Pipeline(
        [
            ("impute", SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True)),
            ("scale", RobustScaler(quantile_range=(10, 90))),
        ]
    )


def feature_names_out(entity_type: str, pre: Pipeline) -> list[str]:
    names = FEATURE_SETS[entity_type][0]
    ind = pre.named_steps["impute"].indicator_
    extra = [f"missing:{names[i]}" for i in ind.features_] if ind is not None else []
    return [*names, *extra]


def rank01(raw_anomaly: NDArray[Any]) -> NDArray[Any]:
    """Higher raw = more anomalous. Returns percentile ranks in (0, 1]."""
    return np.asarray(rankdata(raw_anomaly, method="average") / len(raw_anomaly))


@dataclass
class TrainedModel:
    algorithm: str
    entity_type: str
    pre: Pipeline
    model: Any
    params: dict[str, Any]
    seed: int
    feature_names: list[str]
    train_size: int
    reference_scores: NDArray[Any] = field(repr=False, default_factory=lambda: np.empty(0))

    def raw_anomaly(self, x: NDArray[Any]) -> NDArray[Any]:
        z = self.pre.transform(x)
        return np.asarray(-self.model.score_samples(z))  # higher = more anomalous

    def is_outlier(self, x: NDArray[Any]) -> NDArray[Any]:
        return np.asarray(self.model.predict(self.pre.transform(x)) == -1)

    def scaled(self, x: NDArray[Any]) -> NDArray[Any]:
        return np.asarray(self.pre.transform(x))

    def anomaly_score(self, raw: NDArray[Any]) -> NDArray[Any]:
        """Percentile of each raw score within the training reference distribution (stable for single-row scoring)."""
        ref = np.sort(self.reference_scores)
        return np.asarray(np.searchsorted(ref, raw, side="right") / max(len(ref), 1))


def fit(algorithm: str, entity_type: str, x_train: NDArray[Any], seed: int, **params: Any) -> TrainedModel:
    pre = preprocessor()
    z = pre.fit_transform(x_train)
    if algorithm == "isolation_forest":
        p = {"n_estimators": 300, "max_samples": "auto", "contamination": 0.02, "random_state": seed, **params}
        m: Any = IsolationForest(**p).fit(z)
    elif algorithm == "local_outlier_factor":
        p = {"n_neighbors": 35, "contamination": 0.02, "novelty": True, **params}
        m = LocalOutlierFactor(**p).fit(z)
    else:
        raise ValueError(algorithm)
    tm = TrainedModel(algorithm, entity_type, pre, m, p, seed, feature_names_out(entity_type, pre), len(x_train))
    tm.reference_scores = -m.score_samples(z)
    return tm


def contributions(
    tm: TrainedModel, x: NDArray[Any], top: int = 5, use_shap: bool = False
) -> tuple[list[list[dict[str, Any]]], str]:
    """Per-row top contributing features.

    SHAP TreeExplainer is used for Isolation Forest when requested; otherwise a robust deviation explanation:
    |scaled value| (distance from the training median in units of the 10-90 inter-quantile range).
    """
    z = tm.scaled(x)
    method = "robust_deviation"
    vals = np.abs(z)
    if use_shap and tm.algorithm == "isolation_forest":
        try:
            import shap

            sv = shap.TreeExplainer(tm.model).shap_values(z)
            vals = -np.asarray(sv)  # negative SHAP pushes toward "anomalous" (lower path length)
            method = "shap_tree"
        except Exception:  # pragma: no cover - shap optional at runtime
            method = "robust_deviation"
    out = []
    raw_names = FEATURE_SETS[tm.entity_type][0]
    for i in range(z.shape[0]):
        order = np.argsort(-vals[i])[:top]
        row = []
        for j in order:
            name = tm.feature_names[j]
            orig = x[i, j] if j < len(raw_names) else None
            row.append(
                {
                    "feature": name,
                    "contribution": round(float(vals[i, j]), 4),
                    "direction": "high" if z[i, j] > 0 else "low",
                    "value": None if orig is None or np.isnan(orig) else round(float(orig), 4),
                    "missing": bool(j < len(raw_names) and orig is not None and np.isnan(orig)),
                }
            )
        out.append(row)
    return out, method


def evaluate(scores: NDArray[Any], flags: NDArray[Any], labels: NDArray[Any] | None) -> dict[str, Any]:
    q = np.percentile(scores, [50, 90, 95, 99, 99.9]).tolist() if len(scores) else []
    m: dict[str, Any] = {
        "n": len(scores),
        "flagged": int(flags.sum()),
        "flag_rate": round(float(flags.mean()), 5) if len(flags) else None,
        "score_percentiles": dict(zip(["p50", "p90", "p95", "p99", "p99_9"], [round(v, 5) for v in q], strict=False)),
    }
    if labels is None or labels.sum() == 0 or labels.sum() == len(labels):
        m["labelled"] = False
        return m
    y = labels.astype(int)
    tn, fp, fn, tp = confusion_matrix(y, flags.astype(int), labels=[0, 1]).ravel()
    order = np.argsort(-scores)
    pk = {f"precision_at_{k}": round(float(y[order[:k]].mean()), 4) for k in (25, 50, 100, 200) if k <= len(y)}
    m.update(
        {
            "labelled": True,
            "positives": int(y.sum()),
            "base_rate": round(float(y.mean()), 5),
            "precision": round(float(precision_score(y, flags, zero_division=0)), 4),
            "recall": round(float(recall_score(y, flags, zero_division=0)), 4),
            "f1": round(float(f1_score(y, flags, zero_division=0)), 4),
            "roc_auc": round(float(roc_auc_score(y, scores)), 4),
            "pr_auc": round(float(average_precision_score(y, scores)), 4),
            "false_positive_rate": round(float(fp / (fp + tn)) if (fp + tn) else 0.0, 5),
            "confusion_matrix": {"tp": int(tp), "fp": int(fp), "tn": int(tn), "fn": int(fn)},
            **pk,
        }
    )
    return m


def stability(
    algorithm: str, entity_type: str, x_train: NDArray[Any], x_eval: NDArray[Any], seeds: tuple[int, ...] = (1, 2, 3)
) -> float:
    """Mean pairwise Spearman correlation of holdout scores across random seeds (1.0 = perfectly stable)."""
    runs = [fit(algorithm, entity_type, x_train, s).raw_anomaly(x_eval) for s in seeds]
    cors = [float(spearmanr(runs[i], runs[j]).statistic) for i in range(len(runs)) for j in range(i + 1, len(runs))]
    return round(float(np.mean(cors)), 4)


def save(tm: TrainedModel, model_dir: Path, name: str, version: str) -> tuple[Path, str]:
    model_dir.mkdir(parents=True, exist_ok=True)
    path = model_dir / f"{name}-{version}.joblib"
    joblib.dump(tm, path)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path, expected_sha256: str) -> TrainedModel:
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ValueError(f"Model artifact {path.name} failed integrity check")
    tm: TrainedModel = joblib.load(path)  # nosec - only loads artifacts whose sha256 matches the DB record
    return tm


def snapshot_hash(keys: list[str], rows: list[dict[str, Any]]) -> str:
    h = hashlib.sha256()
    for k, r in zip(keys, rows, strict=True):
        h.update(k.encode())
        h.update(json.dumps(r, sort_keys=True, default=str).encode())
    return h.hexdigest()
