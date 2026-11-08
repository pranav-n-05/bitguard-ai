import uuid
from datetime import datetime

from app.models.base import JobStatus
from app.schemas.common import ORM


class DatasetFileOut(ORM):
    id: uuid.UUID
    original_name: str
    sha256: str
    size_bytes: int
    detected_format: str | None
    detected_encoding: str | None
    integrity_verified_at: datetime | None
    created_at: datetime


class DatasetOut(ORM):
    id: uuid.UUID
    name: str
    description: str | None
    provenance: str
    status: str
    created_at: datetime


class DatasetDetail(DatasetOut):
    files: list[DatasetFileOut]
    jobs: list["JobOut"]


class JobOut(ORM):
    id: uuid.UUID
    dataset_id: uuid.UUID
    dataset_file_id: uuid.UUID
    status: JobStatus
    stage: str
    attempts: int
    total_records: int | None
    processed_records: int
    valid_records: int
    partial_records: int
    quarantined_records: int
    duplicate_records: int
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None
    created_at: datetime


class IngestionErrorOut(ORM):
    id: int
    job_id: uuid.UUID
    record_index: int | None
    raw_record_id: int | None
    field: str | None
    error_code: str
    message: str
    severity: str
    created_at: datetime


DatasetDetail.model_rebuild()
