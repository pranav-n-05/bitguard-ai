"""Dataset registration: streaming upload storage with size limit + sha256, job creation and dispatch."""

import hashlib
import shutil
import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError, ConflictError, NotFoundError, PayloadTooLargeError
from app.ingestion.parsers import SUPPORTED_FORMATS, detect_encoding, detect_format
from app.models import Dataset, DatasetFile, IngestionJob, User
from app.models.base import JobStatus
from app.services import audit

_SAFE_EXT = {".csv", ".json", ".jsonl", ".ndjson", ".xml"}


def _storage_dir(dataset_id: uuid.UUID) -> Path:
    d = get_settings().storage_dir / "datasets" / str(dataset_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


async def store_upload(s: AsyncSession, dataset: Dataset, upload: UploadFile, user: User) -> DatasetFile:
    name = Path(upload.filename or "upload").name  # strip any path components
    ext = Path(name).suffix.lower()
    if ext not in _SAFE_EXT:
        raise AppError(f"Unsupported file extension {ext!r}; allowed: {sorted(_SAFE_EXT)}")
    limit = get_settings().max_upload_mb * 1024 * 1024
    tmp = _storage_dir(dataset.id) / f".upload-{uuid.uuid4().hex}"
    h, size = hashlib.sha256(), 0
    with tmp.open("wb") as f:
        while chunk := await upload.read(1 << 20):
            size += len(chunk)
            if size > limit:
                f.close()
                tmp.unlink(missing_ok=True)
                raise PayloadTooLargeError(f"File exceeds {get_settings().max_upload_mb} MB limit")
            h.update(chunk)
            f.write(chunk)
    return await _register(s, dataset, tmp, name, h.hexdigest(), size, user, move=True)


async def register_local_file(s: AsyncSession, dataset: Dataset, path: Path, user: User | None) -> DatasetFile:
    """Offline bulk path: copy a local file into managed storage."""
    from app.core.hashing import file_sha256

    if path.suffix.lower() not in _SAFE_EXT:
        raise AppError(f"Unsupported file extension {path.suffix!r}")
    dst = _storage_dir(dataset.id) / f".copy-{uuid.uuid4().hex}"
    shutil.copyfile(path, dst)
    return await _register(s, dataset, dst, path.name, file_sha256(dst), dst.stat().st_size, user, move=True)


async def _register(
    s: AsyncSession, dataset: Dataset, tmp: Path, name: str, sha: str, size: int, user: User | None, *, move: bool
) -> DatasetFile:
    dup = (
        await s.execute(select(DatasetFile).where(DatasetFile.dataset_id == dataset.id, DatasetFile.sha256 == sha))
    ).scalar_one_or_none()
    if dup:
        tmp.unlink(missing_ok=True)
        raise ConflictError("Identical file already registered in this dataset", extra={"dataset_file_id": str(dup.id)})
    final = _storage_dir(dataset.id) / f"{sha}{Path(name).suffix.lower()}"
    tmp.replace(final)
    enc = detect_encoding(final)
    fmt = detect_format(final, enc)
    if fmt not in SUPPORTED_FORMATS:
        raise AppError(f"Could not detect a supported format for {name}")
    df = DatasetFile(
        dataset_id=dataset.id,
        original_name=name,
        storage_path=str(final.resolve()),
        sha256=sha,
        size_bytes=size,
        detected_format=fmt,
        detected_encoding=enc,
    )
    s.add(df)
    await s.flush()
    await audit.record(
        s,
        "dataset.file_registered",
        "dataset_file",
        str(df.id),
        actor_id=user.id if user else None,
        actor_email=user.email if user else None,
        details={"dataset_id": str(dataset.id), "sha256": sha, "size": size, "format": fmt, "name": name},
    )
    return df


async def create_jobs(s: AsyncSession, dataset_id: uuid.UUID, user: User | None) -> list[IngestionJob]:
    """Create jobs for files without a completed job; re-queue failed/interrupted jobs (they resume from checkpoint)."""
    ds = await s.get(Dataset, dataset_id)
    if ds is None:
        raise NotFoundError("Dataset not found")
    files = (await s.execute(select(DatasetFile).where(DatasetFile.dataset_id == dataset_id))).scalars().all()
    jobs: list[IngestionJob] = []
    for f in files:
        existing = (
            (
                await s.execute(
                    select(IngestionJob).where(IngestionJob.dataset_file_id == f.id).order_by(IngestionJob.created_at.desc())
                )
            )
            .scalars()
            .first()
        )
        if existing and existing.status in (JobStatus.completed, JobStatus.completed_with_errors):
            continue
        if existing and existing.status in (JobStatus.failed, JobStatus.running, JobStatus.pending):
            existing.status = JobStatus.pending
            jobs.append(existing)
            continue
        j = IngestionJob(dataset_id=dataset_id, dataset_file_id=f.id, triggered_by=user.id if user else None)
        s.add(j)
        jobs.append(j)
    ds.status = "processing" if jobs else ds.status
    await s.flush()
    await audit.record(
        s,
        "dataset.process_requested",
        "dataset",
        str(dataset_id),
        actor_id=user.id if user else None,
        actor_email=user.email if user else None,
        details={"jobs": [str(j.id) for j in jobs]},
    )
    return jobs
