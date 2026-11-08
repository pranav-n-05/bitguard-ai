import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.base import CaseStatus, Severity
from app.schemas.common import ORM


class Links(BaseModel):
    txids: list[str] = Field(default_factory=list, max_length=500)
    addresses: list[str] = Field(default_factory=list, max_length=500)
    alert_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    observation_ids: list[int] = Field(default_factory=list, max_length=500)


class CaseCreate(Links):
    title: str = Field(min_length=3, max_length=255)
    summary: str | None = Field(default=None, max_length=20000)
    priority: Severity = Severity.moderate
    assigned_to: uuid.UUID | None = None


class CasePatch(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=255)
    summary: str | None = Field(default=None, max_length=20000)
    status: CaseStatus | None = None
    priority: Severity | None = None
    assigned_to: uuid.UUID | None = None
    unassign: bool = False
    analyst_decision: str | None = Field(default=None, max_length=20000)


class CaseOut(ORM):
    id: uuid.UUID
    case_number: str
    title: str
    summary: str | None
    status: CaseStatus
    priority: Severity
    created_by: uuid.UUID
    assigned_to: uuid.UUID | None
    analyst_decision: str | None
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None


class NoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=20000)


class EvidenceIn(BaseModel):
    evidence_type: str = Field(pattern="^(transaction|address|observation|alert|raw_record)$")
    reference: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=3, max_length=8000)


class EvidenceOut(ORM):
    id: int
    evidence_type: str
    reference: str
    description: str
    source_dataset_id: uuid.UUID | None
    source_file_id: uuid.UUID | None
    source_file_sha256: str | None
    raw_record_id: int | None
    record_hash: str | None
    txid: str | None
    block_hash: str | None
    analysis_version: dict[str, Any]
    snapshot: dict[str, Any]
    integrity_hash: str
    retrieved_at: datetime
    added_by: uuid.UUID


class ExportIn(BaseModel):
    format: str = Field(default="pdf", pattern="^(pdf|json|csv)$")


class ReportOut(ORM):
    id: uuid.UUID
    report_type: str
    format: str
    investigation_id: uuid.UUID | None
    parameters: dict[str, Any]
    sha256: str
    size_bytes: int
    generated_by: uuid.UUID
    generated_at: datetime


class ReportRequest(BaseModel):
    report_type: str = Field(pattern="^(investigation_summary|alerts|transactions)$")
    format: str = Field(pattern="^(pdf|json|csv)$")
    parameters: dict[str, Any] = Field(default_factory=dict)
