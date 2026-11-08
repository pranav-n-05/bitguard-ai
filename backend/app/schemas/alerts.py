import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.base import AlertStatus, Severity
from app.schemas.common import ORM


class AlertOut(ORM):
    id: uuid.UUID
    category: str
    severity: Severity
    status: AlertStatus
    title: str
    entity_type: str
    entity_key: str
    txid: str | None
    addresses: list[str]
    network_observation_ids: list[int]
    risk_score: int | None
    risk_assessment_id: int | None
    detection_method: str
    triggered_rules: list[dict[str, Any]]
    model_version_id: uuid.UUID | None
    evidence_refs: dict[str, Any]
    explanation: str
    confidence: str
    uncertainty_notes: str
    assigned_to: uuid.UUID | None
    occurrence_count: int
    resolution_note: str | None
    created_at: datetime
    updated_at: datetime


class AlertNoteOut(ORM):
    id: int
    author_id: uuid.UUID
    body: str
    created_at: datetime


class AlertDetail(AlertOut):
    notes: list[AlertNoteOut]
    related_alerts: list[dict[str, Any]]
    allowed_transitions: list[str]


class AlertCreate(BaseModel):
    category: str
    severity: Severity
    title: str = Field(min_length=3, max_length=255)
    entity_type: str = Field(pattern="^(transaction|address|ip|cluster)$")
    entity_key: str = Field(min_length=1, max_length=100)
    explanation: str = Field(min_length=10, max_length=8000)
    txid: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    addresses: list[str] = Field(default_factory=list, max_length=500)


class AlertPatch(BaseModel):
    status: AlertStatus | None = None
    assigned_to: uuid.UUID | None = None
    unassign: bool = False
    note: str | None = Field(default=None, max_length=8000)
    severity: Severity | None = None


class ResolveRequest(BaseModel):
    note: str = Field(min_length=3, max_length=8000)
    false_positive: bool = False
    confirmed_suspicious: bool | None = None
