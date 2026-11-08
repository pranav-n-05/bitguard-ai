"""Read-side helpers shared by intel routers."""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Alert, RiskAssessment
from app.schemas.intel import RiskBrief


async def current_risk(s: AsyncSession, entity_type: str, keys: list[str]) -> dict[str, RiskBrief]:
    if not keys:
        return {}
    rows = await s.execute(
        select(RiskAssessment.entity_key, RiskAssessment.score, RiskAssessment.band, RiskAssessment.id).where(
            RiskAssessment.entity_type == entity_type, RiskAssessment.is_current.is_(True), RiskAssessment.entity_key.in_(keys)
        )
    )
    return {r.entity_key: RiskBrief(score=r.score, band=r.band.value, assessment_id=r.id) for r in rows}


async def alert_counts(s: AsyncSession, txids: list[str]) -> dict[str, int]:
    if not txids:
        return {}
    rows = await s.execute(select(Alert.txid, func.count()).where(Alert.txid.in_(txids)).group_by(Alert.txid))
    return {r[0]: r[1] for r in rows}


def detection_dict(d: Any) -> dict[str, Any]:
    return {
        "id": d.id,
        "pattern": d.pattern,
        "confidence": d.confidence,
        "explanation": d.explanation,
        "limitations": d.limitations,
        "metrics": d.metrics,
        "txids": d.txids[:50],
        "anchor_txid": d.anchor_txid,
    }
