import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import PageDep, SessionDep, require
from app.core.errors import AppError, NotFoundError
from app.database.session import get_sessionmaker
from app.models import AnomalyPrediction, ModelEvaluation, ModelVersion, User
from app.schemas.common import Paginated
from app.services import ml
from app.services.risk_read import analyze_address, analyze_transaction

router = APIRouter(prefix="/ai", tags=["ai"])
Reader = Annotated[User, Depends(require("model.read"))]


def _mv(m: ModelVersion) -> dict[str, Any]:
    return {
        "id": str(m.id),
        "name": m.name,
        "algorithm": m.algorithm,
        "version": m.version,
        "entity_type": m.entity_type,
        "params": m.params,
        "feature_schema": m.feature_schema,
        "training_snapshot": m.training_snapshot,
        "artifact_sha256": m.artifact_sha256,
        "random_seed": m.random_seed,
        "is_active": m.is_active,
        "trained_at": m.trained_at,
        "notes": m.notes,
    }


@router.get("/models")
async def list_models(
    s: SessionDep, _: Reader, entity_type: Annotated[str | None, Query(pattern="^(transaction|address)$")] = None
) -> list[dict[str, Any]]:
    q = select(ModelVersion).order_by(ModelVersion.trained_at.desc())
    if entity_type:
        q = q.where(ModelVersion.entity_type == entity_type)
    out = []
    evs = {e.model_version_id: e for e in (await s.execute(select(ModelEvaluation))).scalars()}
    for m in (await s.execute(q)).scalars():
        d = _mv(m)
        e = evs.get(m.id)
        d["evaluation"] = {"label_source": e.label_source, "metrics": e.metrics, "caveats": e.caveats} if e else None
        out.append(d)
    return out


@router.get("/models/evaluation")
async def evaluations(s: SessionDep, _: Reader) -> list[dict[str, Any]]:
    rows = (
        await s.execute(
            select(ModelEvaluation, ModelVersion)
            .join(ModelVersion, ModelVersion.id == ModelEvaluation.model_version_id)
            .order_by(ModelEvaluation.evaluated_at.desc())
            .limit(50)
        )
    ).all()
    return [
        {
            "model": _mv(m),
            "label_source": e.label_source,
            "metrics": e.metrics,
            "caveats": e.caveats,
            "evaluated_at": e.evaluated_at,
        }
        for e, m in rows
    ]


@router.get("/models/{model_id}")
async def get_model(model_id: uuid.UUID, s: SessionDep, _: Reader) -> dict[str, Any]:
    m = await s.get(ModelVersion, model_id)
    if m is None:
        raise NotFoundError("Model not found")
    d = _mv(m)
    e = (await s.execute(select(ModelEvaluation).where(ModelEvaluation.model_version_id == model_id))).scalars().first()
    d["evaluation"] = {"label_source": e.label_source, "metrics": e.metrics, "caveats": e.caveats} if e else None
    agg: dict[str, float] = {}
    n = 0
    for (contribs,) in await s.execute(
        select(AnomalyPrediction.contributions).where(
            AnomalyPrediction.model_version_id == model_id, AnomalyPrediction.is_outlier.is_(True)
        )
    ):
        n += 1
        for c in contribs:
            agg[c["feature"]] = agg.get(c["feature"], 0) + c["contribution"]
    ranked = sorted(agg.items(), key=lambda kv: -kv[1])[:20]
    d["feature_importance_among_outliers"] = (
        [{"feature": k, "mean_contribution": round(v / n, 4)} for k, v in ranked] if n else []
    )
    d["predictions"] = await s.scalar(
        select(func.count()).select_from(AnomalyPrediction).where(AnomalyPrediction.model_version_id == model_id)
    )
    return d


class TrainRequest(BaseModel):
    entity_type: str = Field(pattern="^(transaction|address)$")
    seed: int = Field(default=42, ge=0, le=2**31 - 1)
    activate: str = Field(default="best", pattern="^(best|none)$")
    notes: str | None = Field(default=None, max_length=2000)


@router.post("/models/train", status_code=201)
async def train(
    body: TrainRequest, s: SessionDep, user: Annotated[User, Depends(require("model.train"))]
) -> list[dict[str, Any]]:
    sm = get_sessionmaker()
    ids = await ml.train(sm, body.entity_type, seed=body.seed, user_id=user.id, activate=body.activate, notes=body.notes)
    await ml.score_all(sm, body.entity_type)
    return [_mv(m) for m in (await s.execute(select(ModelVersion).where(ModelVersion.id.in_(ids)))).scalars()]


@router.post("/models/{model_id}/activate")
async def activate(model_id: uuid.UUID, user: Annotated[User, Depends(require("model.train"))]) -> dict[str, str]:
    sm = get_sessionmaker()
    await ml.activate_model(sm, model_id, user.id, reason="manual activation")
    async with sm() as s:
        mv = await s.get(ModelVersion, model_id)
        assert mv is not None
    await ml.score_all(sm, mv.entity_type)
    return {"status": "activated", "model_id": str(model_id)}


@router.get("/predictions", response_model=Paginated[dict[str, Any]])
async def predictions(
    s: SessionDep,
    page: PageDep,
    _: Reader,
    entity_type: Annotated[str, Query(pattern="^(transaction|address)$")] = "transaction",
    outliers_only: bool = False,
    min_score: Annotated[float | None, Query(ge=0, le=1)] = None,
) -> Paginated[dict[str, Any]]:
    mv = await ml.active_model(s, entity_type)
    if mv is None:
        return Paginated(items=[], total=0, limit=page.limit, offset=page.offset)
    q = select(AnomalyPrediction).where(AnomalyPrediction.model_version_id == mv.id)
    if outliers_only:
        q = q.where(AnomalyPrediction.is_outlier.is_(True))
    if min_score is not None:
        q = q.where(AnomalyPrediction.anomaly_score >= min_score)
    total = await s.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = (await s.execute(q.order_by(AnomalyPrediction.anomaly_score.desc()).limit(page.limit).offset(page.offset))).scalars()
    return Paginated(
        items=[
            {
                "entity_type": p.entity_type,
                "entity_key": p.entity_key,
                "anomaly_score": p.anomaly_score,
                "raw_score": p.raw_score,
                "is_outlier": p.is_outlier,
                "contributions": p.contributions,
                "explanation_method": p.explanation_method,
                "model_version_id": str(mv.id),
            }
            for p in rows
        ],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


class AnalyzeTx(BaseModel):
    txid: str = Field(pattern=r"^[0-9a-fA-F]{64}$")


class AnalyzeAddr(BaseModel):
    address: str = Field(min_length=14, max_length=100)


@router.post("/analyze/transaction")
async def ai_analyze_tx(body: AnalyzeTx, s: SessionDep, _: Annotated[User, Depends(require("intel.analyze"))]) -> dict[str, Any]:
    return await analyze_transaction(s, body.txid.lower())


@router.post("/analyze/address")
async def ai_analyze_addr(
    body: AnalyzeAddr, s: SessionDep, _: Annotated[User, Depends(require("intel.analyze"))]
) -> dict[str, Any]:
    return await analyze_address(s, body.address)


@router.post("/labels/import", summary="Import SYNTHETIC generator labels for evaluation only")
async def import_labels(
    s: SessionDep,
    user: Annotated[User, Depends(require("model.train"))],
    file: Annotated[UploadFile, File()],
    dataset_id: Annotated[uuid.UUID | None, Form()] = None,
) -> dict[str, int]:
    raw = await file.read(50 * 1024 * 1024 + 1)
    if len(raw) > 50 * 1024 * 1024:
        raise AppError("Label file too large")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise AppError("Label file is not valid JSON") from e
    n = await ml.import_labels(s, data, dataset_id, user.id)
    await s.commit()
    return {"imported": n}
