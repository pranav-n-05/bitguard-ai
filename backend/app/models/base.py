"""Declarative base, shared column helpers and enums."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, MetaData, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def bigint_pk() -> Mapped[int]:
    return mapped_column(BigInteger, primary_key=True, autoincrement=True)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class DataQuality(enum.StrEnum):
    valid = "valid"
    partial = "partial"
    invalid = "invalid"
    quarantined = "quarantined"
    unavailable = "unavailable"


class JobStatus(enum.StrEnum):
    pending = "pending"
    running = "running"
    completed = "completed"
    completed_with_errors = "completed_with_errors"
    failed = "failed"


class AlertStatus(enum.StrEnum):
    new = "new"
    acknowledged = "acknowledged"
    under_investigation = "under_investigation"
    escalated = "escalated"
    resolved = "resolved"
    false_positive = "false_positive"


class Severity(enum.StrEnum):
    low = "low"
    moderate = "moderate"
    elevated = "elevated"
    high = "high"


class CaseStatus(enum.StrEnum):
    open = "open"
    in_progress = "in_progress"
    on_hold = "on_hold"
    closed = "closed"


class ReviewStatus(enum.StrEnum):
    unreviewed = "unreviewed"
    confirmed_by_analyst = "confirmed_by_analyst"
    rejected_by_analyst = "rejected_by_analyst"
