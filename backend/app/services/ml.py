"""Model training, evaluation, versioning, activation and batch inference."""

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analytics.features import ADDR_SCHEMA_VERSION, SCHEMA_VERSION
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.ml import engine
from app.models import (
    AddressFeature,
    AnomalyPrediction,
    EvaluationLabel,
    ModelEvaluation,
    ModelVersion,
    Transaction,
    TransactionFeature,
)
from app.services import audit

log = get_logger(__name__)
ALGORITHMS = ("isolation_forest", "local_outlier_factor")
CAVEAT_SYNTH = (
    "Measured against SYNTHETIC injected patterns. Baseline rows are treated as negatives because synthetic labels "
    "are complete by construction. These numbers do not estimate real-world performance."
)
CAVEAT_FEEDBACK = "Measured against analyst feedback labels only; coverage is partial and biased toward reviewed alerts."
CAVEAT_NONE = "No reliable labels available. Only unsupervised diagnostics (score distribution, seed stability) are reported."


async def load_rows(s: AsyncSession, entity_type: str) -> tuple[list[str], list[dict[str, Any]], list[datetime]]:
    if entity_type == "transaction":
        q = (
            select(Transaction.txid, TransactionFeature.features, TransactionFeature.as_of)
            .join(Transaction, Transaction.id == TransactionFeature.transaction_id)
            .where(TransactionFeature.schema_version == SCHEMA_VERSION)
            .order_by(TransactionFeature.as_of, Transaction.id)
        )
    else:
        q = (
            select(AddressFeature.address, AddressFeature.features, AddressFeature.as_of)
            .where(AddressFeature.schema_version == ADDR_SCHEMA_VERSION)
            .order_by(AddressFeature.address)
        )
    rows = (await s.execute(q)).all()
    if entity_type == "address":  # address snapshots share as_of; order by first activity for the time split
        rows = sorted(rows, key=lambda r: (r[1].get("first_seen") or "", r[0]))
    return [r[0] for r in rows], [r[1] for r in rows], [r[2] for r in rows]


async def load_labels(s: AsyncSession, entity_type: str, keys: list[str]) -> tuple[NDArray[Any] | None, str]:
    rows = (
        await s.execute(
            select(EvaluationLabel.entity_key, EvaluationLabel.label, EvaluationLabel.source).where(
                EvaluationLabel.entity_type == entity_type
            )
        )
    ).all()
    if not rows:
        return None, "none"
    sources = {r.source for r in rows}
    lab = {r.entity_key: r.label == "suspicious" for r in rows}
    if "synthetic_injected" in sources:
        return np.array([lab.get(k, False) for k in keys]), "synthetic_injected"
    # Analyst feedback: evaluate only on reviewed rows (return NaN for others; caller masks).
    return np.array([float(lab[k]) if k in lab else np.nan for k in keys]), "analyst_feedback"


async def train(
    sm: async_sessionmaker[AsyncSession],
    entity_type: str,
    *,
    seed: int = 42,
    user_id: uuid.UUID | None = None,
    activate: str = "best",
    notes: str | None = None,
) -> list[uuid.UUID]:
    if entity_type not in engine.FEATURE_SETS:
        raise AppError("entity_type must be transaction or address")
    async with sm() as s:
        keys, rows, _ = await load_rows(s, entity_type)
        labels, label_source = await load_labels(s, entity_type, keys)
    if len(rows) < 50:
        raise AppError(f"Not enough feature rows to train ({len(rows)} < 50); ingest and process data first")
    x = engine.matrix(rows, entity_type)
    cut = int(len(rows) * engine.TRAIN_FRACTION)
    x_train, x_hold = x[:cut], x[cut:]
    snap = {
        "rows": len(rows),
        "train_rows": cut,
        "holdout_rows": len(rows) - cut,
        "split": "time-ordered",
        "feature_hash": engine.snapshot_hash(keys, rows),
        "first_key": keys[0],
        "last_key": keys[-1],
        "feature_schema_version": SCHEMA_VERSION if entity_type == "transaction" else ADDR_SCHEMA_VERSION,
    }
    version = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    model_dir = Path(get_settings().model_dir)
    results: list[tuple[uuid.UUID, float]] = []
    for algo in ALGORITHMS:
        tm = engine.fit(algo, entity_type, x_train, seed)
        hold_raw = tm.raw_anomaly(x_hold)
        hold_flags = tm.is_outlier(x_hold)
        y = None
        if labels is not None:
            yh = labels[cut:]
            if label_source == "analyst_feedback":
                mask = ~np.isnan(yh.astype(float))
                hold_raw, hold_flags, y = hold_raw[mask], hold_flags[mask], yh[mask].astype(bool)
            else:
                y = yh.astype(bool)
        metrics = engine.evaluate(hold_raw, hold_flags, y)
        metrics["seed_stability_spearman"] = engine.stability(algo, entity_type, x_train, x_hold)
        metrics["label_source"] = label_source if metrics.get("labelled") else "none"
        name = f"{entity_type}_{algo}"
        path, sha = engine.save(tm, model_dir, name, version)
        mid = uuid.uuid4()
        caveat = {"synthetic_injected": CAVEAT_SYNTH, "analyst_feedback": CAVEAT_FEEDBACK}.get(
            metrics["label_source"], CAVEAT_NONE
        )
        async with sm() as s, s.begin():
            s.add(
                ModelVersion(
                    id=mid,
                    name=name,
                    algorithm=algo,
                    version=version,
                    entity_type=entity_type,
                    params={k: v for k, v in tm.params.items()},
                    artifact_path=str(path),
                    artifact_sha256=sha,
                    feature_schema={
                        "features": tm.feature_names,
                        "log_scaled": sorted(engine.FEATURE_SETS[entity_type][1]),
                        "missing_strategy": "median-impute + indicator",
                        "scaler": "RobustScaler(10,90)",
                    },
                    training_snapshot=snap,
                    random_seed=seed,
                    trained_by=user_id,
                    notes=notes,
                )
            )
            await s.flush()
            s.add(ModelEvaluation(model_version_id=mid, label_source=metrics["label_source"], metrics=metrics, caveats=caveat))
            await audit.record(
                s,
                "model.trained",
                "model_version",
                str(mid),
                actor_id=user_id,
                details={"name": name, "version": version, "pr_auc": metrics.get("pr_auc")},
            )
        key = metrics.get("pr_auc") if metrics.get("labelled") else metrics["seed_stability_spearman"]
        results.append((mid, float(key or 0.0)))
        log.info(
            "model_trained", name=name, version=version, **{k: metrics.get(k) for k in ("pr_auc", "roc_auc", "precision_at_50")}
        )
    if activate == "best":
        best = max(results, key=lambda r: r[1])[0]
        await activate_model(sm, best, user_id, reason="best holdout metric among compared algorithms")
    return [r[0] for r in results]


async def activate_model(
    sm: async_sessionmaker[AsyncSession], model_id: uuid.UUID, user_id: uuid.UUID | None, reason: str
) -> None:
    async with sm() as s, s.begin():
        m = await s.get(ModelVersion, model_id)
        if m is None:
            raise AppError("Model not found")
        await s.execute(update(ModelVersion).where(ModelVersion.entity_type == m.entity_type).values(is_active=False))
        m.is_active = True
        await audit.record(s, "model.activated", "model_version", str(model_id), actor_id=user_id, details={"reason": reason})


async def active_model(s: AsyncSession, entity_type: str) -> ModelVersion | None:
    return (
        (await s.execute(select(ModelVersion).where(ModelVersion.is_active.is_(True), ModelVersion.entity_type == entity_type)))
        .scalars()
        .first()
    )


def load_trained(mv: ModelVersion) -> engine.TrainedModel:
    return engine.load(Path(mv.artifact_path), mv.artifact_sha256)


async def score_all(sm: async_sessionmaker[AsyncSession], entity_type: str, shap_top: int = 300) -> int:
    async with sm() as s:
        mv = await active_model(s, entity_type)
        if mv is None:
            return 0
        keys, rows, _ = await load_rows(s, entity_type)
    if not rows:
        return 0
    tm = load_trained(mv)
    x = engine.matrix(rows, entity_type)
    raw = tm.raw_anomaly(x)
    score = tm.anomaly_score(raw)
    flags = tm.is_outlier(x)
    contrib, method = engine.contributions(tm, x)
    top = np.argsort(-raw)[:shap_top]
    shap_m = method
    if len(top):
        shap_c, shap_m = engine.contributions(tm, x[top], use_shap=True)
        for idx, c in zip(top, shap_c, strict=True):
            contrib[idx] = c
    top_set = {int(i) for i in top}
    preds = [
        {
            "model_version_id": mv.id,
            "entity_type": entity_type,
            "entity_key": k,
            "raw_score": round(float(r), 6),
            "anomaly_score": round(float(sc), 6),
            "is_outlier": bool(f),
            "contributions": c,
            "explanation_method": shap_m if i in top_set else method,
        }
        for i, (k, r, sc, f, c) in enumerate(zip(keys, raw, score, flags, contrib, strict=True))
    ]
    async with sm() as s, s.begin():
        await s.execute(delete(AnomalyPrediction).where(AnomalyPrediction.model_version_id == mv.id))
        for i in range(0, len(preds), 2000):
            await s.execute(pg_insert(AnomalyPrediction).values(preds[i : i + 2000]))
    return len(preds)


async def ml_stage(sm: async_sessionmaker[AsyncSession], dataset_id: uuid.UUID) -> None:
    for et in ("transaction", "address"):
        async with sm() as s:
            mv = await active_model(s, et)
        if mv is None:
            try:
                await train(sm, et, notes=f"auto-trained after first processed dataset {dataset_id}")
            except AppError as e:
                log.warning("auto_train_skipped", entity_type=et, reason=e.detail)
                continue
        n = await score_all(sm, et)
        log.info("scored", entity_type=et, n=n)


async def import_labels(s: AsyncSession, labels: dict[str, Any], dataset_id: uuid.UUID | None, user_id: uuid.UUID | None) -> int:
    """Import a SYNTHETIC generator labels file (evaluation only)."""
    if not labels.get("meta", {}).get("synthetic"):
        raise AppError("Only synthetic generator label files (meta.synthetic=true) can be imported as injected labels")
    rows = []
    benign = {"coinjoin_like", "large_normal"}
    for txid, pattern in labels.get("txids", {}).items():
        rows.append(
            {
                "entity_type": "transaction",
                "entity_key": txid,
                "pattern": pattern,
                "label": "benign" if pattern in benign else "suspicious",
            }
        )
    for p in labels.get("patterns", []):
        for a in p.get("addresses", []):
            rows.append(
                {
                    "entity_type": "address",
                    "entity_key": a,
                    "pattern": p["pattern"],
                    "label": "suspicious" if p.get("suspicious") else "benign",
                }
            )
    dedup = {(r["entity_type"], r["entity_key"]): r for r in rows}
    vals = [{**r, "source": "synthetic_injected", "dataset_id": dataset_id, "created_by": user_id} for r in dedup.values()]
    for i in range(0, len(vals), 2000):
        st = pg_insert(EvaluationLabel).values(vals[i : i + 2000])
        await s.execute(
            st.on_conflict_do_update(
                index_elements=["entity_type", "entity_key", "source"],
                set_={"label": st.excluded.label, "pattern": st.excluded.pattern},
            )
        )
    await audit.record(s, "labels.imported", "evaluation_labels", None, actor_id=user_id, details={"count": len(vals)})
    return len(vals)
