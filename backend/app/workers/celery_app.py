"""Celery application. Each task builds its own engine (Celery prefork + asyncio safety)."""

import asyncio
import uuid
from typing import Any

from celery import Celery
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.logging import configure_logging

configure_logging()
_s = get_settings()
celery_app = Celery("bitguard", broker=_s.redis_url, backend=_s.redis_url)
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_default_retry_delay=5,
    broker_connection_retry_on_startup=True,
)


async def run_ingestion(job_id: uuid.UUID) -> dict[str, Any]:
    from app.ingestion.service import IngestionService
    from app.services.pipeline import run_post_ingestion

    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    try:
        sm = async_sessionmaker(engine, expire_on_commit=False)
        job = await IngestionService(sm).run(job_id)
        await run_post_ingestion(sm, job.dataset_id)
        return {"job_id": str(job_id), "status": job.status.value}
    finally:
        await engine.dispose()


@celery_app.task(  # type: ignore[misc]
    name="bitguard.ingest",
    bind=True,
    max_retries=3,
    autoretry_for=(ConnectionError, OSError),
    retry_backoff=True,
    retry_backoff_max=120,
)
def ingest_task(self: Any, job_id: str) -> dict[str, Any]:
    return asyncio.run(run_ingestion(uuid.UUID(job_id)))
