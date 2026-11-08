"""Canonical blockchain-layer and network-layer entities.

`transactions` is the canonical transaction table (spec §6 calls it canonical_transactions).
Address rows describe *addresses*, never wallets or people.
"""

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
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, DataQuality, ReviewStatus, TimestampMixin, bigint_pk, uuid_pk
from app.models.ingestion import str_enum


class Transaction(Base):
    __tablename__ = "transactions"
    id: Mapped[int] = bigint_pk()
    txid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    block_height: Mapped[int | None] = mapped_column(Integer, index=True)
    block_hash: Mapped[str | None] = mapped_column(String(64))
    confirmations: Mapped[int | None] = mapped_column(Integer)
    version: Mapped[int | None] = mapped_column(Integer)
    locktime: Mapped[int | None] = mapped_column(BigInteger)
    size: Mapped[int | None] = mapped_column(Integer)
    vsize: Mapped[int | None] = mapped_column(Integer)
    weight: Mapped[int | None] = mapped_column(Integer)
    total_input_sat: Mapped[int] = mapped_column(BigInteger)
    total_output_sat: Mapped[int] = mapped_column(BigInteger)
    fee_sat: Mapped[int] = mapped_column(BigInteger)
    input_count: Mapped[int] = mapped_column(Integer)
    output_count: Mapped[int] = mapped_column(Integer)
    script_type: Mapped[str | None] = mapped_column(String(32))
    data_quality: Mapped[DataQuality] = mapped_column(str_enum(DataQuality))
    content_hash: Mapped[str] = mapped_column(String(64))
    source_raw_record_id: Mapped[int] = mapped_column(ForeignKey("raw_records.id"))
    dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("datasets.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    inputs: Mapped[list["TransactionInput"]] = relationship(lazy="noload", order_by="TransactionInput.position")
    outputs: Mapped[list["TransactionOutput"]] = relationship(lazy="noload", order_by="TransactionOutput.position")


class TransactionInput(Base):
    __tablename__ = "transaction_inputs"
    __table_args__ = (UniqueConstraint("transaction_id", "position"),)
    id: Mapped[int] = bigint_pk()
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    address: Mapped[str] = mapped_column(String(100), index=True)
    amount_sat: Mapped[int] = mapped_column(BigInteger)
    script_type: Mapped[str | None] = mapped_column(String(32))


class TransactionOutput(Base):
    __tablename__ = "transaction_outputs"
    __table_args__ = (UniqueConstraint("transaction_id", "position"),)
    id: Mapped[int] = bigint_pk()
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    address: Mapped[str] = mapped_column(String(100), index=True)
    amount_sat: Mapped[int] = mapped_column(BigInteger)
    script_type: Mapped[str | None] = mapped_column(String(32))


class Address(Base):
    __tablename__ = "addresses"
    address: Mapped[str] = mapped_column(String(100), primary_key=True)
    address_type: Mapped[str] = mapped_column(String(16))  # p2pkh | p2sh | p2wpkh | p2wsh | p2tr | unknown
    network: Mapped[str] = mapped_column(String(16), default="mainnet")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IpEntity(Base):
    __tablename__ = "ip_entities"
    ip: Mapped[str] = mapped_column(INET, primary_key=True)
    version: Mapped[int] = mapped_column(Integer)
    is_private: Mapped[bool] = mapped_column(default=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AsnEntity(Base):
    __tablename__ = "asn_entities"
    asn: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GeoEntity(Base):
    __tablename__ = "geo_entities"
    country_code: Mapped[str] = mapped_column(String(2), primary_key=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class NetworkObservation(Base):
    """One network-layer sighting of a transaction. Co-occurrence only — never identity attribution."""

    __tablename__ = "network_observations"
    __table_args__ = (
        Index("ix_netobs_src_time", "src_ip", "observed_at"),
        Index("ix_netobs_dst_time", "dst_ip", "observed_at"),
    )
    id: Mapped[int] = bigint_pk()
    obs_hash: Mapped[str] = mapped_column(String(64), unique=True)
    txid: Mapped[str] = mapped_column(String(64), index=True)
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id", ondelete="SET NULL"), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    src_ip: Mapped[str] = mapped_column(INET)
    dst_ip: Mapped[str] = mapped_column(INET)
    src_port: Mapped[int] = mapped_column(Integer)
    dst_port: Mapped[int] = mapped_column(Integer)
    protocol: Mapped[str | None] = mapped_column(String(32))
    asn: Mapped[int | None] = mapped_column(BigInteger, index=True)
    geo_country: Mapped[str | None] = mapped_column(String(2), index=True)
    extra: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    data_quality: Mapped[DataQuality] = mapped_column(str_enum(DataQuality))
    source_raw_record_id: Mapped[int] = mapped_column(ForeignKey("raw_records.id"))
    dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("datasets.id"), index=True)


class AddressCluster(TimestampMixin, Base):
    """Probabilistic investigative grouping. Never a confirmed real-world entity."""

    __tablename__ = "address_clusters"
    id: Mapped[uuid.UUID] = uuid_pk()
    method: Mapped[str] = mapped_column(String(48), index=True)  # common_input | change_output | behavioural
    confidence: Mapped[float] = mapped_column(Float)
    size: Mapped[int] = mapped_column(Integer)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    limitations: Mapped[str] = mapped_column(Text)
    review_status: Mapped[ReviewStatus] = mapped_column(str_enum(ReviewStatus), default=ReviewStatus.unreviewed)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    run_id: Mapped[str] = mapped_column(String(64), index=True)


class ClusterMembership(Base):
    __tablename__ = "cluster_memberships"
    cluster_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("address_clusters.id", ondelete="CASCADE"), primary_key=True
    )
    address: Mapped[str] = mapped_column(String(100), primary_key=True, index=True)
    link_confidence: Mapped[float] = mapped_column(Float)
    evidence_txids: Mapped[list[str]] = mapped_column(JSONB, default=list)
