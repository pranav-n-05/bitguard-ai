"""Post-ingestion pipeline stages. Stages are added per milestone; each is idempotent."""

import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.logging import get_logger
from app.models import Dataset

log = get_logger(__name__)
Stage = Callable[[async_sessionmaker[AsyncSession], uuid.UUID], Awaitable[None]]
STAGES: list[tuple[str, Stage]] = []


def register_default_stages() -> None:
    from app.alerts.engine import alert_stage
    from app.services.analytics_stage import analytics_stage
    from app.services.ml import ml_stage
    from app.services.risk import risk_stage

    if not STAGES:
        STAGES.extend([("analytics", analytics_stage), ("ml", ml_stage), ("risk", risk_stage), ("alerts", alert_stage)])


async def run_post_ingestion(sm: async_sessionmaker[AsyncSession], dataset_id: uuid.UUID) -> None:
    register_default_stages()
    for name, stage in STAGES:
        log.info("pipeline_stage_start", stage=name, dataset_id=str(dataset_id))
        await stage(sm, dataset_id)
    async with sm() as s, s.begin():
        ds = await s.get(Dataset, dataset_id)
        if ds:
            ds.status = "processed"


async def dispatch(job_id: uuid.UUID) -> str | None:
    """Run inline when BITGUARD_CELERY_EAGER (tests / single-process), else enqueue on Celery."""
    from app.core.config import get_settings

    if get_settings().celery_eager:
        from app.workers.celery_app import run_ingestion

        try:
            await run_ingestion(job_id)
        except Exception:  # failure is recorded on the job row, same as for an async worker
            log.exception("eager_ingestion_failed", job_id=str(job_id))
        return None
    from app.workers.celery_app import ingest_task

    return str(ingest_task.delay(str(job_id)).id)
