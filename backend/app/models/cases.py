"""Alerts, alert rules, investigations, evidence, reports, system configuration."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import AlertStatus, Base, CaseStatus, Severity, TimestampMixin, bigint_pk, uuid_pk
from app.models.ingestion import str_enum


class AlertRule(TimestampMixin, Base):
    __tablename__ = "alert_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    category: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(default=True)
    thresholds: Mapped[dict[str, Any]] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer, default=1)


class Alert(TimestampMixin, Base):
    __tablename__ = "alerts"
    id: Mapped[uuid.UUID] = uuid_pk()
    dedup_key: Mapped[str] = mapped_column(String(64), unique=True)
    category: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[Severity] = mapped_column(str_enum(Severity), index=True)
    status: Mapped[AlertStatus] = mapped_column(str_enum(AlertStatus), default=AlertStatus.new, index=True)
    title: Mapped[str] = mapped_column(String(255))
    entity_type: Mapped[str] = mapped_column(String(16))
    entity_key: Mapped[str] = mapped_column(String(100), index=True)
    txid: Mapped[str | None] = mapped_column(String(64), index=True)
    addresses: Mapped[list[str]] = mapped_column(JSONB, default=list)
    network_observation_ids: Mapped[list[int]] = mapped_column(JSONB, default=list)
    risk_score: Mapped[int | None] = mapped_column(Integer)
    risk_assessment_id: Mapped[int | None] = mapped_column(ForeignKey("risk_assessments.id"))
    detection_method: Mapped[str] = mapped_column(String(64))
    triggered_rules: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    model_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("model_versions.id"))
    evidence_refs: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    explanation: Mapped[str] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(String(16))
    uncertainty_notes: Mapped[str] = mapped_column(Text)
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1)
    resolution_note: Mapped[str | None] = mapped_column(Text)


class AlertNote(Base):
    __tablename__ = "alert_notes"
    id: Mapped[int] = bigint_pk()
    alert_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("alerts.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AlertLink(Base):
    __tablename__ = "alert_links"
    alert_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("alerts.id", ondelete="CASCADE"), primary_key=True)
    related_alert_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("alerts.id", ondelete="CASCADE"), primary_key=True)
    reason: Mapped[str] = mapped_column(String(255))


class Investigation(TimestampMixin, Base):
    __tablename__ = "investigations"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_number: Mapped[str] = mapped_column(String(32), unique=True)
    title: Mapped[str] = mapped_column(String(255))
    summary: Mapped[str | None] = mapped_column(Text)
    status: Mapped[CaseStatus] = mapped_column(str_enum(CaseStatus), default=CaseStatus.open, index=True)
    priority: Mapped[Severity] = mapped_column(str_enum(Severity), default=Severity.moderate, index=True)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    analyst_decision: Mapped[str | None] = mapped_column(Text)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InvestigationTransaction(Base):
    __tablename__ = "investigation_transactions"
    investigation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("investigations.id", ondelete="CASCADE"), primary_key=True)
    txid: Mapped[str] = mapped_column(String(64), primary_key=True)
    added_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InvestigationAddress(Base):
    __tablename__ = "investigation_addresses"
    investigation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("investigations.id", ondelete="CASCADE"), primary_key=True)
    address: Mapped[str] = mapped_column(String(100), primary_key=True)
    added_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InvestigationAlert(Base):
    __tablename__ = "investigation_alerts"
    investigation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("investigations.id", ondelete="CASCADE"), primary_key=True)
    alert_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("alerts.id", ondelete="CASCADE"), primary_key=True)
    added_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InvestigationObservation(Base):
    __tablename__ = "investigation_observations"
    investigation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("investigations.id", ondelete="CASCADE"), primary_key=True)
    observation_id: Mapped[int] = mapped_column(ForeignKey("network_observations.id", ondelete="CASCADE"), primary_key=True)
    added_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InvestigationNote(Base):
    __tablename__ = "investigation_notes"
    id: Mapped[int] = bigint_pk()
    investigation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("investigations.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EvidenceRecord(Base):
    """Append-only evidence reference with provenance and integrity hash (UPDATE/DELETE blocked by trigger)."""

    __tablename__ = "evidence_records"
    id: Mapped[int] = bigint_pk()
    investigation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("investigations.id", ondelete="CASCADE"), index=True)
    evidence_type: Mapped[str] = mapped_column(String(32))  # transaction | address | observation | alert | raw_record | report
    reference: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text)
    source_dataset_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    source_file_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    source_file_sha256: Mapped[str | None] = mapped_column(String(64))
    raw_record_id: Mapped[int | None] = mapped_column(ForeignKey("raw_records.id"))
    record_hash: Mapped[str | None] = mapped_column(String(64))
    txid: Mapped[str | None] = mapped_column(String(64))
    block_hash: Mapped[str | None] = mapped_column(String(64))
    analysis_version: Mapped[dict[str, Any]] = mapped_column(JSONB)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    integrity_hash: Mapped[str] = mapped_column(String(64))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    added_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))


class ReportRecord(Base):
    __tablename__ = "report_records"
    id: Mapped[uuid.UUID] = uuid_pk()
    report_type: Mapped[str] = mapped_column(String(32))  # investigation_summary | alerts | transactions
    format: Mapped[str] = mapped_column(String(8))  # pdf | csv | json
    investigation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("investigations.id", ondelete="SET NULL"), index=True)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB)
    storage_path: Mapped[str] = mapped_column(String(1024))
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    generated_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SystemConfig(TimestampMixin, Base):
    __tablename__ = "system_config"
    __table_args__ = (UniqueConstraint("key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64))
    value: Mapped[dict[str, Any]] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
