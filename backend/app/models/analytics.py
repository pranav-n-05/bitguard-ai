"""Feature stores, models, predictions, risk assessments."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
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

from app.models.base import Base, Severity, bigint_pk, uuid_pk
from app.models.ingestion import str_enum


class TransactionFeature(Base):
    __tablename__ = "transaction_features"
    __table_args__ = (UniqueConstraint("transaction_id", "schema_version"),)
    id: Mapped[int] = bigint_pk()
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id", ondelete="CASCADE"), index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    schema_version: Mapped[str] = mapped_column(String(16))
    features: Mapped[dict[str, Any]] = mapped_column(JSONB)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AddressFeature(Base):
    __tablename__ = "address_features"
    __table_args__ = (UniqueConstraint("address", "as_of", "schema_version"),)
    id: Mapped[int] = bigint_pk()
    address: Mapped[str] = mapped_column(String(100), index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    schema_version: Mapped[str] = mapped_column(String(16))
    features: Mapped[dict[str, Any]] = mapped_column(JSONB)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NetworkFeature(Base):
    __tablename__ = "network_features"
    __table_args__ = (UniqueConstraint("entity_type", "entity_key", "as_of", "schema_version"),)
    id: Mapped[int] = bigint_pk()
    entity_type: Mapped[str] = mapped_column(String(16))  # ip | asn | country
    entity_key: Mapped[str] = mapped_column(String(64), index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    schema_version: Mapped[str] = mapped_column(String(16))
    features: Mapped[dict[str, Any]] = mapped_column(JSONB)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CorrelationIndicator(Base):
    """Network-blockchain co-occurrence indicator. Investigative lead, not attribution."""

    __tablename__ = "correlation_indicators"
    __table_args__ = (Index("ix_corr_entity", "entity_type", "entity_key"),)
    id: Mapped[int] = bigint_pk()
    indicator_type: Mapped[str] = mapped_column(String(48), index=True)
    entity_type: Mapped[str] = mapped_column(String(16))
    entity_key: Mapped[str] = mapped_column(String(100))
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    strength: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB)
    evidence_refs: Mapped[dict[str, Any]] = mapped_column(JSONB)
    limitations: Mapped[str] = mapped_column(Text)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ModelVersion(Base):
    __tablename__ = "model_versions"
    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(64), index=True)  # e.g. tx_isolation_forest
    algorithm: Mapped[str] = mapped_column(String(48))
    version: Mapped[str] = mapped_column(String(32))
    entity_type: Mapped[str] = mapped_column(String(16))  # transaction | address
    params: Mapped[dict[str, Any]] = mapped_column(JSONB)
    feature_schema: Mapped[dict[str, Any]] = mapped_column(JSONB)
    training_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    artifact_path: Mapped[str] = mapped_column(String(1024))
    artifact_sha256: Mapped[str] = mapped_column(String(64))
    random_seed: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(default=False, index=True)
    trained_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    trained_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    notes: Mapped[str | None] = mapped_column(Text)


class ModelEvaluation(Base):
    __tablename__ = "model_evaluations"
    id: Mapped[int] = bigint_pk()
    model_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("model_versions.id", ondelete="CASCADE"), index=True)
    label_source: Mapped[str] = mapped_column(String(48))  # synthetic_injected | analyst_feedback | none
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB)
    caveats: Mapped[str] = mapped_column(Text)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AnomalyPrediction(Base):
    __tablename__ = "anomaly_predictions"
    __table_args__ = (UniqueConstraint("model_version_id", "entity_type", "entity_key"),)
    id: Mapped[int] = bigint_pk()
    model_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("model_versions.id", ondelete="CASCADE"), index=True)
    entity_type: Mapped[str] = mapped_column(String(16))
    entity_key: Mapped[str] = mapped_column(String(100), index=True)
    raw_score: Mapped[float] = mapped_column(Float)
    anomaly_score: Mapped[float] = mapped_column(Float)  # 0..1 rank-normalised, NOT a probability
    is_outlier: Mapped[bool] = mapped_column(default=False)
    contributions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    explanation_method: Mapped[str] = mapped_column(String(32))
    predicted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RiskAssessment(Base):
    """Append-only; recalculation creates a new row that supersedes the previous one."""

    __tablename__ = "risk_assessments"
    __table_args__ = (Index("ix_risk_entity_current", "entity_type", "entity_key", "is_current"),)
    id: Mapped[int] = bigint_pk()
    entity_type: Mapped[str] = mapped_column(String(16))
    entity_key: Mapped[str] = mapped_column(String(100))
    score: Mapped[int] = mapped_column(Integer, index=True)
    band: Mapped[Severity] = mapped_column(str_enum(Severity))
    uncertainty: Mapped[float] = mapped_column(Float)
    rule_version: Mapped[str] = mapped_column(String(32))
    weights: Mapped[dict[str, Any]] = mapped_column(JSONB)
    model_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("model_versions.id"))
    explanation: Mapped[str] = mapped_column(Text)
    limitations: Mapped[str] = mapped_column(Text)
    evidence_refs: Mapped[dict[str, Any]] = mapped_column(JSONB)
    recommended_action: Mapped[str] = mapped_column(Text)
    is_current: Mapped[bool] = mapped_column(default=True)
    supersedes_id: Mapped[int | None] = mapped_column(ForeignKey("risk_assessments.id"))
    change_reason: Mapped[str | None] = mapped_column(Text)
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RiskComponent(Base):
    __tablename__ = "risk_components"
    id: Mapped[int] = bigint_pk()
    assessment_id: Mapped[int] = mapped_column(ForeignKey("risk_assessments.id", ondelete="CASCADE"), index=True)
    component: Mapped[str] = mapped_column(String(48))
    raw_value: Mapped[float | None] = mapped_column(Float)
    normalised: Mapped[float] = mapped_column(Float)
    weight: Mapped[float] = mapped_column(Float)
    contribution: Mapped[float] = mapped_column(Float)
    rationale: Mapped[str] = mapped_column(Text)
    available: Mapped[bool] = mapped_column(default=True)


_ = (BigInteger, UUID)


class GraphDetection(Base):
    """Structural graph pattern (fan-in/out, cycle, peel chain, layering). Investigative lead only."""

    __tablename__ = "graph_detections"
    id: Mapped[int] = bigint_pk()
    pattern: Mapped[str] = mapped_column(String(48), index=True)
    anchor_txid: Mapped[str | None] = mapped_column(String(64), index=True)
    txids: Mapped[list[str]] = mapped_column(JSONB)
    addresses: Mapped[list[str]] = mapped_column(JSONB)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB)
    confidence: Mapped[float] = mapped_column(Float)
    explanation: Mapped[str] = mapped_column(Text)
    limitations: Mapped[str] = mapped_column(Text)
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AnalysisRun(Base):
    """One execution of a derived-analytics stage; the latest successful run per stage is 'current'."""

    __tablename__ = "analysis_runs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    stage: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(16))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EvaluationLabel(Base):
    """Ground truth used ONLY for evaluation (never as a training feature)."""

    __tablename__ = "evaluation_labels"
    __table_args__ = (UniqueConstraint("entity_type", "entity_key", "source"),)
    id: Mapped[int] = bigint_pk()
    entity_type: Mapped[str] = mapped_column(String(16))
    entity_key: Mapped[str] = mapped_column(String(100), index=True)
    label: Mapped[str] = mapped_column(String(16))  # suspicious | benign
    pattern: Mapped[str | None] = mapped_column(String(48))
    source: Mapped[str] = mapped_column(String(32))  # synthetic_injected | analyst_feedback
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
