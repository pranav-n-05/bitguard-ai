"""Read-side risk/explanation assembly and on-demand analysis."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.ml import engine
from app.models import (
    Address,
    AddressFeature,
    Alert,
    AnomalyPrediction,
    RiskAssessment,
    RiskComponent,
    Transaction,
    TransactionFeature,
)
from app.services import ml


async def risk_detail(s: AsyncSession, entity_type: str, key: str, history: int = 10) -> dict[str, Any]:
    rows = (
        (
            await s.execute(
                select(RiskAssessment)
                .where(RiskAssessment.entity_type == entity_type, RiskAssessment.entity_key == key)
                .order_by(RiskAssessment.assessed_at.desc(), RiskAssessment.id.desc())
                .limit(history)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return {
            "available": False,
            "entity_type": entity_type,
            "entity_key": key,
            "reason": "No risk assessment yet (data not processed or entity not scored).",
        }
    cur = next((r for r in rows if r.is_current), rows[0])
    comps = (await s.execute(select(RiskComponent).where(RiskComponent.assessment_id == cur.id))).scalars().all()
    pred = (
        (
            await s.execute(
                select(AnomalyPrediction).where(
                    AnomalyPrediction.model_version_id == cur.model_version_id, AnomalyPrediction.entity_key == key
                )
            )
        )
        .scalars()
        .first()
        if cur.model_version_id
        else None
    )
    alerts = (
        await s.execute(
            select(Alert.id, Alert.category, Alert.status, Alert.severity).where((Alert.entity_key == key) | (Alert.txid == key))
        )
    ).all()
    return {
        "available": True,
        "entity_type": entity_type,
        "entity_key": key,
        "assessment_id": cur.id,
        "score": cur.score,
        "band": cur.band.value,
        "uncertainty": cur.uncertainty,
        "rule_version": cur.rule_version,
        "weights": cur.weights,
        "model_version_id": str(cur.model_version_id) if cur.model_version_id else None,
        "explanation": cur.explanation,
        "limitations": cur.limitations,
        "recommended_action": cur.recommended_action,
        "evidence_refs": cur.evidence_refs,
        "assessed_at": cur.assessed_at,
        "components": [
            {
                "component": c.component,
                "normalised": c.normalised,
                "weight": c.weight,
                "contribution": c.contribution,
                "raw_value": c.raw_value,
                "rationale": c.rationale,
                "available": c.available,
            }
            for c in comps
        ],
        "anomaly": {
            "anomaly_score": pred.anomaly_score,
            "raw_score": pred.raw_score,
            "is_outlier": pred.is_outlier,
            "top_features": pred.contributions,
            "explanation_method": pred.explanation_method,
            "note": "Outlier rank versus the training distribution, not a probability.",
        }
        if pred
        else None,
        "history": [
            {
                "assessment_id": r.id,
                "score": r.score,
                "band": r.band.value,
                "assessed_at": r.assessed_at,
                "is_current": r.is_current,
                "change_reason": r.change_reason,
                "supersedes_id": r.supersedes_id,
            }
            for r in rows
        ],
        "alerts": [
            {"id": str(a.id), "category": a.category, "status": a.status.value, "severity": a.severity.value} for a in alerts
        ],
        "data_layers": {
            "observed": "transaction/inputs/outputs/network observations",
            "derived": "features",
            "heuristic": "graph detections, correlation indicators, clusters",
            "ml": "anomaly prediction",
            "analyst": "alert decisions and case notes",
        },
    }


async def _rescore(s: AsyncSession, entity_type: str, features: dict[str, Any]) -> dict[str, Any] | None:
    mv = await ml.active_model(s, entity_type)
    if mv is None:
        return None
    tm = ml.load_trained(mv)
    x = engine.matrix([features], entity_type)
    raw = tm.raw_anomaly(x)
    contrib, method = engine.contributions(tm, x, use_shap=True)
    return {
        "model_version_id": str(mv.id),
        "model": f"{mv.name}@{mv.version}",
        "raw_score": round(float(raw[0]), 6),
        "anomaly_score": round(float(tm.anomaly_score(raw)[0]), 6),
        "is_outlier": bool(tm.is_outlier(x)[0]),
        "top_features": contrib[0],
        "explanation_method": method,
        "reproducible": True,
    }


async def analyze_transaction(s: AsyncSession, txid: str) -> dict[str, Any]:
    t = (await s.execute(select(Transaction).where(Transaction.txid == txid))).scalar_one_or_none()
    if t is None:
        raise NotFoundError("Transaction not found in ingested data")
    f = (await s.execute(select(TransactionFeature).where(TransactionFeature.transaction_id == t.id))).scalars().first()
    return {
        "txid": txid,
        "features": f.features if f else None,
        "feature_as_of": f.as_of if f else None,
        "prediction": await _rescore(s, "transaction", f.features) if f else None,
        "risk": await risk_detail(s, "transaction", txid),
    }


async def analyze_address(s: AsyncSession, address: str) -> dict[str, Any]:
    if await s.get(Address, address) is None:
        raise NotFoundError("Address not present in ingested data")
    f = (await s.execute(select(AddressFeature).where(AddressFeature.address == address))).scalars().first()
    return {
        "address": address,
        "features": f.features if f else None,
        "prediction": await _rescore(s, "address", f.features) if f else None,
        "risk": await risk_detail(s, "address", address),
    }
