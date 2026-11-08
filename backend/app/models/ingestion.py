"""Datasets, files, immutable raw staging records, jobs, errors, checkpoints, dead letters."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, DataQuality, JobStatus, TimestampMixin, bigint_pk, uuid_pk


def str_enum(e: type) -> Enum:
    return Enum(e, native_enum=False, length=32, values_callable=lambda x: [m.value for m in x])


class Dataset(TimestampMixin, Base):
    __tablename__ = "datasets"
    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    provenance: Mapped[str] = mapped_column(String(32), default="synthetic")  # synthetic | historical | external
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(32), default="registered")


class DatasetFile(TimestampMixin, Base):
    __tablename__ = "dataset_files"
    __table_args__ = (UniqueConstraint("dataset_id", "sha256"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    original_name: Mapped[str] = mapped_column(String(512))
    storage_path: Mapped[str] = mapped_column(String(1024))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    detected_format: Mapped[str | None] = mapped_column(String(16))
    detected_encoding: Mapped[str | None] = mapped_column(String(32))
    integrity_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RawRecord(Base):
    """Immutable staging copy of every source record exactly as parsed (UPDATE/DELETE blocked by trigger)."""

    __tablename__ = "raw_records"
    __table_args__ = (
        UniqueConstraint("dataset_file_id", "record_index"),
        Index("ix_raw_records_dataset_hash", "dataset_id", "content_hash"),
    )
    id: Mapped[int] = bigint_pk()
    dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"))
    dataset_file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dataset_files.id", ondelete="CASCADE"))
    record_index: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    data_quality: Mapped[DataQuality] = mapped_column(str_enum(DataQuality))
    is_duplicate: Mapped[bool] = mapped_column(default=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IngestionJob(TimestampMixin, Base):
    __tablename__ = "ingestion_jobs"
    id: Mapped[uuid.UUID] = uuid_pk()
    dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    dataset_file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dataset_files.id", ondelete="CASCADE"))
    status: Mapped[JobStatus] = mapped_column(str_enum(JobStatus), default=JobStatus.pending, index=True)
    stage: Mapped[str] = mapped_column(String(32), default="queued")
    attempts: Mapped[int] = mapped_column(default=0)
    total_records: Mapped[int | None] = mapped_column(Integer)
    processed_records: Mapped[int] = mapped_column(default=0)
    valid_records: Mapped[int] = mapped_column(default=0)
    partial_records: Mapped[int] = mapped_column(default=0)
    quarantined_records: Mapped[int] = mapped_column(default=0)
    duplicate_records: Mapped[int] = mapped_column(default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    triggered_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    celery_task_id: Mapped[str | None] = mapped_column(String(64))


class IngestionError(Base):
    __tablename__ = "ingestion_errors"
    id: Mapped[int] = bigint_pk()
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ingestion_jobs.id", ondelete="CASCADE"), index=True)
    dataset_file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dataset_files.id", ondelete="CASCADE"))
    record_index: Mapped[int | None] = mapped_column(Integer)
    raw_record_id: Mapped[int | None] = mapped_column(ForeignKey("raw_records.id"))
    field: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str] = mapped_column(String(64), index=True)
    message: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(16))  # error -> quarantined, warning -> partial
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IngestionCheckpoint(Base):
    __tablename__ = "ingestion_checkpoints"
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ingestion_jobs.id", ondelete="CASCADE"), primary_key=True)
    last_record_index: Mapped[int] = mapped_column(Integer, default=-1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class DeadLetter(Base):
    __tablename__ = "dead_letters"
    id: Mapped[int] = bigint_pk()
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    stage: Mapped[str] = mapped_column(String(32))
    record_index: Mapped[int | None] = mapped_column(Integer)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    error: Mapped[str] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
