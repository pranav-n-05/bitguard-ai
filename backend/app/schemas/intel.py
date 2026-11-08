import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator

from app.models.base import DataQuality
from app.schemas.common import ORM

IpStr = Annotated[str, BeforeValidator(str)]


class RiskBrief(BaseModel):
    score: int
    band: str
    assessment_id: int


class TransactionOut(ORM):
    txid: str
    first_seen_at: datetime
    block_height: int | None
    total_input_sat: int
    total_output_sat: int
    fee_sat: int
    input_count: int
    output_count: int
    script_type: str | None
    data_quality: DataQuality
    dataset_id: uuid.UUID
    risk: RiskBrief | None = None
    alert_count: int = 0


class IoOut(ORM):
    position: int
    address: str
    amount_sat: int
    script_type: str | None


class ObservationOut(ORM):
    id: int
    observed_at: datetime
    src_ip: IpStr
    dst_ip: IpStr
    src_port: int
    dst_port: int
    protocol: str | None
    asn: int | None
    geo_country: str | None
    data_quality: DataQuality


class EvidenceProvenance(BaseModel):
    dataset_id: uuid.UUID
    dataset_name: str
    provenance: str
    dataset_file_id: uuid.UUID
    file_name: str
    file_sha256: str
    raw_record_id: int
    record_index: int
    record_hash: str


class TransactionDetail(TransactionOut):
    block_hash: str | None
    vsize: int | None
    version: int | None
    locktime: int | None
    content_hash: str
    inputs: list[IoOut]
    outputs: list[IoOut]
    observations: list[ObservationOut]
    features: dict[str, Any] | None
    feature_schema_version: str | None
    graph_detections: list[dict[str, Any]]
    provenance: EvidenceProvenance
    data_labels: list[str]


class AddressOut(BaseModel):
    address: str
    address_type: str
    network: str
    first_seen_at: datetime
    last_seen_at: datetime
    features: dict[str, Any] | None
    clusters: list[dict[str, Any]]
    correlations: list[dict[str, Any]]
    graph_detections: list[dict[str, Any]]
    risk: RiskBrief | None
    investigations: list[uuid.UUID]
    notice: str


class IndicatorOut(ORM):
    id: int
    indicator_type: str
    entity_type: str
    entity_key: str
    window_start: datetime
    window_end: datetime
    strength: float
    confidence: float
    metrics: dict[str, Any]
    evidence_refs: dict[str, Any]
    limitations: str


class DetectionOut(ORM):
    id: int
    pattern: str
    anchor_txid: str | None
    txids: list[str]
    addresses: list[str]
    metrics: dict[str, Any]
    confidence: float
    explanation: str
    limitations: str
    window_start: datetime | None
    window_end: datetime | None


class ClusterOut(ORM):
    id: uuid.UUID
    method: str
    confidence: float
    size: int
    evidence: dict[str, Any]
    limitations: str
    review_status: str
    created_at: datetime


class ClusterDetail(ClusterOut):
    members: list[dict[str, Any]]


class AnalyzeRequest(BaseModel):
    txids: list[str] | None = None
    addresses: list[str] | None = None
