from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text

from app.api.deps import SessionDep, require
from app.core.config import get_settings
from app.models import (
    Address,
    Dataset,
    IngestionJob,
    NetworkObservation,
    RawRecord,
    Transaction,
    User,
)
from app.models.base import DataQuality, JobStatus

router = APIRouter(tags=["system"])


@router.get("/health", summary="Liveness/readiness probe (no auth)")
async def health(s: SessionDep) -> dict[str, Any]:
    db_ok = True
    try:
        await s.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    redis_ok: bool | None = None
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(get_settings().redis_url, socket_connect_timeout=1)
        redis_ok = bool(await r.ping())
        await r.aclose()  # type: ignore[attr-defined]
    except Exception:
        redis_ok = False
    return {"status": "ok" if db_ok else "degraded", "database": db_ok, "redis": redis_ok}


@router.get("/system/status")
async def status(s: SessionDep, _: Annotated[User, Depends(require("dataset.read"))]) -> dict[str, Any]:
    jobs = dict((await s.execute(select(IngestionJob.status, func.count()).group_by(IngestionJob.status))).tuples().all())
    quality = dict(
        (await s.execute(select(RawRecord.data_quality, func.count()).group_by(RawRecord.data_quality))).tuples().all()
    )
    return {
        "environment": get_settings().env,
        "mode": "offline-bulk",
        "live_node_connected": False,
        "datasets": await s.scalar(select(func.count()).select_from(Dataset)),
        "jobs": {k.value: jobs.get(k, 0) for k in JobStatus},
        "raw_records_by_quality": {k.value: quality.get(k, 0) for k in DataQuality},
    }


@router.get("/system/metrics")
async def metrics(s: SessionDep, _: Annotated[User, Depends(require("dataset.read"))]) -> dict[str, Any]:
    return {
        "transactions": await s.scalar(select(func.count()).select_from(Transaction)),
        "addresses": await s.scalar(select(func.count()).select_from(Address)),
        "network_observations": await s.scalar(select(func.count()).select_from(NetworkObservation)),
        "raw_records": await s.scalar(select(func.count()).select_from(RawRecord)),
    }
