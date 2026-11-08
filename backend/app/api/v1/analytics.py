from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.api.deps import SessionDep, require
from app.models import (
    Address,
    Alert,
    AnalysisRun,
    AnomalyPrediction,
    CorrelationIndicator,
    Dataset,
    GraphDetection,
    IngestionJob,
    Investigation,
    ModelVersion,
    NetworkObservation,
    RawRecord,
    RiskAssessment,
    Transaction,
    User,
)
from app.models.base import AlertStatus, CaseStatus, DataQuality, JobStatus, Severity

router = APIRouter(prefix="/analytics", tags=["analytics"])
Reader = Annotated[User, Depends(require("intel.read"))]


@router.get("/overview")
async def overview(s: SessionDep, _: Reader) -> dict[str, Any]:
    last = (
        (await s.execute(select(AnalysisRun).where(AnalysisRun.status == "completed").order_by(AnalysisRun.finished_at.desc())))
        .scalars()
        .first()
    )
    rng = (await s.execute(select(func.min(Transaction.first_seen_at), func.max(Transaction.first_seen_at)))).one()
    q = dict((await s.execute(select(RawRecord.data_quality, func.count()).group_by(RawRecord.data_quality))).tuples().all())
    jobs = dict((await s.execute(select(IngestionJob.status, func.count()).group_by(IngestionJob.status))).tuples().all())
    open_alerts = dict(
        (
            await s.execute(
                select(Alert.severity, func.count())
                .where(
                    Alert.status.in_(
                        [AlertStatus.new, AlertStatus.acknowledged, AlertStatus.under_investigation, AlertStatus.escalated]
                    )
                )
                .group_by(Alert.severity)
            )
        )
        .tuples()
        .all()
    )
    provenances = sorted(set((await s.execute(select(Dataset.provenance).distinct())).scalars()))
    active_model = (await s.execute(select(ModelVersion).where(ModelVersion.is_active.is_(True)))).scalars().all()
    return {
        "data_labels": provenances or ["unavailable"],
        "time_range": {"start": rng[0], "end": rng[1]} if rng[0] else None,
        "counts": {
            "datasets": await s.scalar(select(func.count()).select_from(Dataset)),
            "transactions": await s.scalar(select(func.count()).select_from(Transaction)),
            "addresses": await s.scalar(select(func.count()).select_from(Address)),
            "network_observations": await s.scalar(select(func.count()).select_from(NetworkObservation)),
            "graph_detections": await s.scalar(select(func.count()).select_from(GraphDetection)),
            "correlation_indicators": await s.scalar(select(func.count()).select_from(CorrelationIndicator)),
            "open_cases": await s.scalar(
                select(func.count()).select_from(Investigation).where(Investigation.status != CaseStatus.closed)
            ),
        },
        "record_quality": {k.value: q.get(k, 0) for k in DataQuality},
        "ingestion_jobs": {k.value: jobs.get(k, 0) for k in JobStatus},
        "open_alerts_by_severity": {k.value: open_alerts.get(k, 0) for k in Severity},
        "last_analysis_run": {"id": last.id, "finished_at": last.finished_at, "stats": last.stats} if last else None,
        "active_models": [{"id": str(m.id), "name": m.name, "version": m.version} for m in active_model],
    }


@router.get("/transaction-volume")
async def transaction_volume(
    s: SessionDep,
    _: Reader,
    bucket: Annotated[str, Query(pattern="^(hour|day|week)$")] = "day",
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict[str, Any]:
    b = func.date_trunc(bucket, Transaction.first_seen_at).label("b")
    q = select(b, func.count(), func.sum(Transaction.total_output_sat), func.sum(Transaction.fee_sat)).group_by("b").order_by("b")
    if start:
        q = q.where(Transaction.first_seen_at >= start)
    if end:
        q = q.where(Transaction.first_seen_at <= end)
    rows = await s.execute(q)
    return {
        "bucket": bucket,
        "series": [{"t": t, "tx_count": c, "value_sat": int(v or 0), "fee_sat": int(f or 0)} for t, c, v, f in rows],
    }


@router.get("/risk-distribution")
async def risk_distribution(
    s: SessionDep, _: Reader, entity_type: Annotated[str, Query(pattern="^(transaction|address)$")] = "transaction"
) -> dict[str, Any]:
    cur = (RiskAssessment.is_current.is_(True), RiskAssessment.entity_type == entity_type)
    bands = dict(
        (await s.execute(select(RiskAssessment.band, func.count()).where(*cur).group_by(RiskAssessment.band))).tuples().all()
    )
    hist = await s.execute(
        select((RiskAssessment.score / 10).label("bin"), func.count()).where(*cur).group_by("bin").order_by("bin")
    )
    n = sum(bands.values())
    return {
        "entity_type": entity_type,
        "assessed": n,
        "available": n > 0,
        "bands": {k.value: bands.get(k, 0) for k in Severity},
        "histogram": [{"range": f"{b * 10}-{min(b * 10 + 9, 100)}", "count": c} for b, c in hist],
        "note": "Bands are prioritisation tiers, not probabilities of criminal conduct.",
    }


@router.get("/anomalies")
async def anomalies(
    s: SessionDep,
    _: Reader,
    entity_type: Annotated[str, Query(pattern="^(transaction|address)$")] = "transaction",
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
) -> dict[str, Any]:
    model = (
        (await s.execute(select(ModelVersion).where(ModelVersion.is_active.is_(True), ModelVersion.entity_type == entity_type)))
        .scalars()
        .first()
    )
    if model is None:
        return {"available": False, "reason": "No active model for this entity type", "items": [], "histogram": []}
    base = select(AnomalyPrediction).where(AnomalyPrediction.model_version_id == model.id)
    top = (await s.execute(base.order_by(AnomalyPrediction.anomaly_score.desc()).limit(limit))).scalars().all()
    # Rank-normalised scores are uniform by construction, so the histogram uses the raw model score.
    lo, hi = (
        await s.execute(
            select(func.min(AnomalyPrediction.raw_score), func.max(AnomalyPrediction.raw_score)).where(
                AnomalyPrediction.model_version_id == model.id
            )
        )
    ).one()
    width = ((hi - lo) / 20) if lo is not None and hi is not None and hi > lo else 1.0
    lo = lo or 0.0
    hist = await s.execute(
        select(func.least(func.floor((AnomalyPrediction.raw_score - lo) / width), 19).label("bin"), func.count())
        .where(AnomalyPrediction.model_version_id == model.id)
        .group_by("bin")
        .order_by("bin")
    )
    return {
        "available": True,
        "model": {"id": str(model.id), "name": model.name, "version": model.version},
        "items": [
            {
                "entity_key": p.entity_key,
                "anomaly_score": p.anomaly_score,
                "is_outlier": p.is_outlier,
                "top_features": p.contributions[:3],
            }
            for p in top
        ],
        "histogram": [{"bin_start": round(lo + float(b) * width, 4), "count": c} for b, c in hist],
        "histogram_basis": "raw model score (higher = more anomalous)",
        "note": "Anomaly score is a rank-normalised outlier measure (0-1), not a probability of wrongdoing.",
    }


@router.get("/network-patterns")
async def network_patterns(s: SessionDep, _: Reader) -> dict[str, Any]:
    by_type = await s.execute(
        select(CorrelationIndicator.indicator_type, func.count(), func.avg(CorrelationIndicator.confidence)).group_by(
            CorrelationIndicator.indicator_type
        )
    )
    det = await s.execute(
        select(GraphDetection.pattern, func.count(), func.avg(GraphDetection.confidence)).group_by(GraphDetection.pattern)
    )
    return {
        "correlation_indicators": [{"type": t, "count": c, "avg_confidence": round(float(a), 3)} for t, c, a in by_type],
        "graph_patterns": [{"pattern": p, "count": c, "avg_confidence": round(float(a), 3)} for p, c, a in det],
    }
