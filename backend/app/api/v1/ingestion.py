import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy import func, select

from app.api.deps import PageDep, SessionDep, apply_sort, require
from app.core.errors import NotFoundError
from app.models import Dataset, DatasetFile, IngestionError, IngestionJob, User
from app.models.base import JobStatus
from app.schemas.common import Paginated
from app.schemas.ingestion import DatasetDetail, DatasetOut, IngestionErrorOut, JobOut
from app.services import audit, datasets
from app.services.pipeline import dispatch

router = APIRouter(prefix="/ingestion", tags=["ingestion"])


@router.post("/datasets", response_model=DatasetDetail, status_code=201, summary="Register a dataset and upload file(s)")
async def create_dataset(
    s: SessionDep,
    user: Annotated[User, Depends(require("dataset.upload"))],
    name: Annotated[str, Form(min_length=1, max_length=255)],
    files: Annotated[list[UploadFile], File(description="CSV / JSON / JSONL / XML files")],
    description: Annotated[str | None, Form(max_length=4000)] = None,
    provenance: Annotated[str, Form(pattern="^(synthetic|historical|external)$")] = "synthetic",
    dataset_id: Annotated[uuid.UUID | None, Form(description="Append files to an existing dataset")] = None,
) -> DatasetDetail:
    if dataset_id:
        ds = await s.get(Dataset, dataset_id)
        if ds is None:
            raise NotFoundError("Dataset not found")
    else:
        ds = Dataset(name=name, description=description, provenance=provenance, created_by=user.id)
        s.add(ds)
        await s.flush()
        await audit.record(
            s,
            "dataset.created",
            "dataset",
            str(ds.id),
            actor_id=user.id,
            actor_email=user.email,
            details={"name": name, "provenance": provenance},
        )
    for f in files:
        await datasets.store_upload(s, ds, f, user)
    await s.commit()
    return await _detail(s, ds.id)


async def _detail(s: SessionDep, dataset_id: uuid.UUID) -> DatasetDetail:
    ds = await s.get(Dataset, dataset_id)
    if ds is None:
        raise NotFoundError("Dataset not found")
    files = (
        (await s.execute(select(DatasetFile).where(DatasetFile.dataset_id == ds.id).order_by(DatasetFile.created_at)))
        .scalars()
        .all()
    )
    jobs = (
        (await s.execute(select(IngestionJob).where(IngestionJob.dataset_id == ds.id).order_by(IngestionJob.created_at)))
        .scalars()
        .all()
    )
    return DatasetDetail.model_validate({**DatasetOut.model_validate(ds).model_dump(), "files": files, "jobs": jobs})


@router.get("/datasets", response_model=Paginated[DatasetOut])
async def list_datasets(
    s: SessionDep,
    page: PageDep,
    _: Annotated[User, Depends(require("dataset.read"))],
    provenance: str | None = None,
    status: str | None = None,
) -> Paginated[DatasetOut]:
    q = select(Dataset)
    if provenance:
        q = q.where(Dataset.provenance == provenance)
    if status:
        q = q.where(Dataset.status == status)
    total = await s.scalar(select(func.count()).select_from(q.subquery())) or 0
    q = apply_sort(q, Dataset, page.sort, {"created_at", "name", "status"}, Dataset.created_at.desc())
    rows = (await s.execute(q.limit(page.limit).offset(page.offset))).scalars().all()
    return Paginated(items=[DatasetOut.model_validate(r) for r in rows], total=total, limit=page.limit, offset=page.offset)


@router.get("/datasets/{dataset_id}", response_model=DatasetDetail)
async def get_dataset(
    dataset_id: uuid.UUID, s: SessionDep, _: Annotated[User, Depends(require("dataset.read"))]
) -> DatasetDetail:
    return await _detail(s, dataset_id)


@router.post(
    "/datasets/{dataset_id}/process",
    response_model=list[JobOut],
    status_code=202,
    summary="Start or resume processing (resumes from last checkpoint)",
)
async def process_dataset(
    dataset_id: uuid.UUID, s: SessionDep, user: Annotated[User, Depends(require("dataset.process"))]
) -> list[JobOut]:
    jobs = await datasets.create_jobs(s, dataset_id, user)
    await s.commit()
    ids = [j.id for j in jobs]
    for j in jobs:
        task_id = await dispatch(j.id)
        if task_id:
            j.celery_task_id = task_id
    await s.commit()
    s.expire_all()
    rows = (await s.execute(select(IngestionJob).where(IngestionJob.id.in_(ids)))).scalars().all()
    return [JobOut.model_validate(r) for r in rows]


@router.get("/jobs", response_model=Paginated[JobOut])
async def list_jobs(
    s: SessionDep,
    page: PageDep,
    _: Annotated[User, Depends(require("dataset.read"))],
    dataset_id: uuid.UUID | None = None,
    status: JobStatus | None = None,
) -> Paginated[JobOut]:
    q = select(IngestionJob)
    if dataset_id:
        q = q.where(IngestionJob.dataset_id == dataset_id)
    if status:
        q = q.where(IngestionJob.status == status)
    total = await s.scalar(select(func.count()).select_from(q.subquery())) or 0
    q = apply_sort(q, IngestionJob, page.sort, {"created_at", "status", "processed_records"}, IngestionJob.created_at.desc())
    rows = (await s.execute(q.limit(page.limit).offset(page.offset))).scalars().all()
    return Paginated(items=[JobOut.model_validate(r) for r in rows], total=total, limit=page.limit, offset=page.offset)


@router.get("/jobs/{job_id}", response_model=JobOut)
async def get_job(job_id: uuid.UUID, s: SessionDep, _: Annotated[User, Depends(require("dataset.read"))]) -> JobOut:
    j = await s.get(IngestionJob, job_id)
    if j is None:
        raise NotFoundError("Job not found")
    return JobOut.model_validate(j)


@router.get("/errors", response_model=Paginated[IngestionErrorOut])
async def list_errors(
    s: SessionDep,
    page: PageDep,
    _: Annotated[User, Depends(require("dataset.read"))],
    job_id: uuid.UUID | None = None,
    error_code: Annotated[str | None, Query(max_length=64)] = None,
    severity: Annotated[str | None, Query(pattern="^(error|warning)$")] = None,
) -> Paginated[IngestionErrorOut]:
    q = select(IngestionError)
    if job_id:
        q = q.where(IngestionError.job_id == job_id)
    if error_code:
        q = q.where(IngestionError.error_code == error_code)
    if severity:
        q = q.where(IngestionError.severity == severity)
    total = await s.scalar(select(func.count()).select_from(q.subquery())) or 0
    q = apply_sort(q, IngestionError, page.sort, {"record_index", "error_code", "created_at"}, IngestionError.id)
    rows = (await s.execute(q.limit(page.limit).offset(page.offset))).scalars().all()
    return Paginated(items=[IngestionErrorOut.model_validate(r) for r in rows], total=total, limit=page.limit, offset=page.offset)
