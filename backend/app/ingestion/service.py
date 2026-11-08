"""Idempotent, resumable bulk ingestion of a dataset file.

Guarantees:
- Each source record gets exactly one immutable raw_records row (unique on file + record_index).
- Batches commit atomically together with the checkpoint, so a crash resumes exactly after the
  last committed batch with no gaps and no duplicates.
- Every rejected/flagged record has ingestion_errors rows with reasons. Nothing is dropped silently.
- Transient DB failures are retried with exponential backoff; records that still fail are written
  to dead_letters and counted.
"""

import asyncio
import ipaddress
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.hashing import content_hash, file_sha256
from app.core.logging import get_logger
from app.ingestion.address_codec import classify_address
from app.ingestion.normalize import Issue, NormalisedRecord, normalise
from app.ingestion.parsers import ParseFailure, detect_encoding, detect_format, iter_records
from app.models import (
    Address,
    AsnEntity,
    DatasetFile,
    DeadLetter,
    GeoEntity,
    IngestionCheckpoint,
    IngestionError,
    IngestionJob,
    IpEntity,
    NetworkObservation,
    RawRecord,
    Transaction,
    TransactionInput,
    TransactionOutput,
)
from app.models.base import DataQuality, JobStatus

log = get_logger(__name__)


class IntegrityFailure(Exception):
    pass


@dataclass
class _Item:
    index: int
    raw: dict[str, Any]
    norm: NormalisedRecord | None
    parse_error: str | None
    content_hash: str
    quality: DataQuality
    duplicate: bool = False
    raw_id: int | None = None


def _count_records(path: Path, fmt: str, encoding: str) -> int | None:
    if fmt == "jsonl":
        with path.open("r", encoding=encoding) as f:
            return sum(1 for line in f if line.strip())
    if fmt == "csv":
        n = sum(1 for _ in iter_records(path, fmt, encoding))
        return n
    return None


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s)


class IngestionService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        batch_size: int | None = None,
        fail_hook: Callable[[int], None] | None = None,
    ) -> None:
        s = get_settings()
        self.sm = sessionmaker
        self.batch_size = batch_size or s.ingestion_checkpoint_every
        self.max_retries = s.ingestion_max_retries
        self.fail_hook = fail_hook  # test hook: called with batch start index; may raise to simulate a crash

    async def run(self, job_id: uuid.UUID) -> IngestionJob:
        async with self.sm() as s:
            job = await s.get(IngestionJob, job_id)
            if job is None:
                raise ValueError(f"job {job_id} not found")
            dfile = await s.get(DatasetFile, job.dataset_file_id)
            assert dfile is not None
            path = Path(dfile.storage_path)
            if not path.exists() or file_sha256(path) != dfile.sha256:
                job.status, job.error_message, job.finished_at = (
                    JobStatus.failed,
                    "File integrity check failed (sha256 mismatch or missing)",
                    datetime.now(UTC),
                )
                await s.commit()
                raise IntegrityFailure(job.error_message)
            dfile.integrity_verified_at = datetime.now(UTC)
            enc = dfile.detected_encoding or detect_encoding(path)
            fmt = dfile.detected_format or detect_format(path, enc)
            dfile.detected_encoding, dfile.detected_format = enc, fmt
            cp = await s.get(IngestionCheckpoint, job.id)
            if cp is None:
                cp = IngestionCheckpoint(job_id=job.id, last_record_index=-1)
                s.add(cp)
            if job.total_records is None:
                job.total_records = _count_records(path, fmt, enc)
            job.status, job.stage, job.attempts = JobStatus.running, "ingesting", job.attempts + 1
            job.started_at = job.started_at or datetime.now(UTC)
            job.error_message = None
            start_after = cp.last_record_index
            dataset_id, file_id = job.dataset_id, dfile.id
            await s.commit()

        log.info("ingestion_start", job_id=str(job_id), fmt=fmt, resume_after=start_after)
        batch: list[tuple[int, dict[str, Any] | ParseFailure]] = []
        try:
            for item in iter_records(path, fmt, enc, start_after=start_after):
                batch.append(item)
                if len(batch) >= self.batch_size:
                    await self._commit_batch_with_retry(job_id, dataset_id, file_id, batch)
                    batch = []
            if batch:
                await self._commit_batch_with_retry(job_id, dataset_id, file_id, batch)
        except Exception as e:
            async with self.sm() as s:
                job = await s.get(IngestionJob, job_id)
                assert job is not None
                job.status, job.error_message = JobStatus.failed, f"{type(e).__name__}: {e}"[:2000]
                await s.commit()
            log.exception("ingestion_failed", job_id=str(job_id))
            raise

        async with self.sm() as s:
            job = await s.get(IngestionJob, job_id)
            assert job is not None
            n_err = await s.scalar(select(func.count()).select_from(IngestionError).where(IngestionError.job_id == job_id))
            job.status = JobStatus.completed_with_errors if (job.quarantined_records or n_err) else JobStatus.completed
            job.stage, job.finished_at = "ingested", datetime.now(UTC)
            if job.total_records is None:
                job.total_records = job.processed_records
            await s.commit()
            await s.refresh(job)
            log.info("ingestion_done", job_id=str(job_id), processed=job.processed_records, quarantined=job.quarantined_records)
            return job

    async def _commit_batch_with_retry(
        self, job_id: uuid.UUID, dataset_id: uuid.UUID, file_id: uuid.UUID, batch: list[tuple[int, dict[str, Any] | ParseFailure]]
    ) -> None:
        if self.fail_hook:
            self.fail_hook(batch[0][0])
        delay = 0.2
        for attempt in range(self.max_retries + 1):
            try:
                async with self.sm() as s, s.begin():
                    await self._process_batch(s, job_id, dataset_id, file_id, batch)
                return
            except (OperationalError, DBAPIError) as e:
                if attempt == self.max_retries:
                    log.warning("batch_failed_fallback_single", job_id=str(job_id), error=str(e)[:300])
                    break
                await asyncio.sleep(delay)
                delay *= 2
        for item in batch:  # isolate poison records
            try:
                async with self.sm() as s, s.begin():
                    await self._process_batch(s, job_id, dataset_id, file_id, [item])
            except (OperationalError, DBAPIError) as e:
                async with self.sm() as s, s.begin():
                    payload = item[1] if isinstance(item[1], dict) else {"_unparsed": item[1].raw}
                    s.add(
                        DeadLetter(
                            job_id=job_id,
                            stage="ingest",
                            record_index=item[0],
                            payload=_jsonable(payload),
                            error=str(e)[:4000],
                            attempts=self.max_retries + 1,
                        )
                    )
                    job = await s.get(IngestionJob, job_id, with_for_update=True)
                    assert job is not None
                    job.processed_records += 1
                    job.quarantined_records += 1
                    cp = await s.get(IngestionCheckpoint, job_id, with_for_update=True)
                    assert cp is not None
                    cp.last_record_index = max(cp.last_record_index, item[0])

    async def _process_batch(
        self,
        s: AsyncSession,
        job_id: uuid.UUID,
        dataset_id: uuid.UUID,
        file_id: uuid.UUID,
        batch: list[tuple[int, dict[str, Any] | ParseFailure]],
    ) -> None:
        items: list[_Item] = []
        for idx, rec in batch:
            if isinstance(rec, ParseFailure):
                raw = {"_unparsed": rec.raw}
                items.append(_Item(idx, raw, None, rec.message, content_hash(raw), DataQuality.invalid))
            else:
                n = normalise(rec)
                h = n.record_hash if n.quality != DataQuality.quarantined else content_hash(rec)
                items.append(_Item(idx, _jsonable(rec), n, None, h, n.quality))

        # --- duplicates (same canonical content already in this dataset, or earlier in batch)
        hashes = [i.content_hash for i in items]
        existing = set(
            (
                await s.execute(
                    select(RawRecord.content_hash).where(RawRecord.dataset_id == dataset_id, RawRecord.content_hash.in_(hashes))
                )
            ).scalars()
        )
        seen: set[str] = set()
        for it in items:
            if it.content_hash in existing or it.content_hash in seen:
                it.duplicate = True
            seen.add(it.content_hash)

        # --- txid content conflicts (same txid, different blockchain content)
        good = [i for i in items if i.norm and not i.duplicate and i.quality in (DataQuality.valid, DataQuality.partial)]
        txids = list({i.norm.data["txid"] for i in good if i.norm})
        known: dict[str, tuple[int, str]] = {
            r.txid: (r.id, r.content_hash)
            for r in (
                await s.execute(
                    select(Transaction.id, Transaction.txid, Transaction.content_hash).where(Transaction.txid.in_(txids))
                )
            )
        }
        first_in_batch: dict[str, str] = {}
        for it in good:
            assert it.norm
            txid, th = it.norm.data["txid"], it.norm.tx_hash
            ref = known.get(txid, (0, first_in_batch.get(txid, th)))[1]
            if ref != th:
                it.norm.err("txid", "txid_content_conflict", "same txid already ingested with different inputs/outputs/fee")
                it.quality = DataQuality.quarantined
            first_in_batch.setdefault(txid, th)

        # --- immutable raw staging
        raw_rows = [
            {
                "dataset_id": dataset_id,
                "dataset_file_id": file_id,
                "record_index": i.index,
                "content_hash": i.content_hash,
                "payload": i.raw,
                "data_quality": i.quality,
                "is_duplicate": i.duplicate,
            }
            for i in items
        ]
        res = await s.execute(
            pg_insert(RawRecord)
            .values(raw_rows)
            .on_conflict_do_nothing(index_elements=["dataset_file_id", "record_index"])
            .returning(RawRecord.id, RawRecord.record_index)
        )
        ids = {r.record_index: r.id for r in res}
        for it in items:
            it.raw_id = ids.get(it.index)
        items = [i for i in items if i.raw_id is not None]  # already committed earlier (resume overlap)

        # --- errors
        err_rows = []
        for it in items:
            issues = (
                [Issue(None, "parse_error", it.parse_error, "error")] if it.parse_error else (it.norm.issues if it.norm else [])
            )
            if it.duplicate:
                issues = [
                    *issues,
                    Issue(None, "duplicate_record", "identical record already ingested in this dataset", "warning"),
                ]
            err_rows += [
                {
                    "job_id": job_id,
                    "dataset_file_id": file_id,
                    "record_index": it.index,
                    "raw_record_id": it.raw_id,
                    "field": x.field,
                    "error_code": x.code,
                    "message": x.message,
                    "severity": x.severity,
                }
                for x in issues
            ]
        if err_rows:
            await s.execute(pg_insert(IngestionError).values(err_rows))

        canon = [i for i in items if i.norm and not i.duplicate and i.quality in (DataQuality.valid, DataQuality.partial)]
        await self._write_canonical(s, dataset_id, canon)

        # --- progress + checkpoint (same DB transaction as the data)
        job = await s.get(IngestionJob, job_id, with_for_update=True)
        assert job is not None
        job.processed_records += len(items)
        job.valid_records += sum(1 for i in items if i.quality == DataQuality.valid and not i.duplicate)
        job.partial_records += sum(1 for i in items if i.quality == DataQuality.partial and not i.duplicate)
        job.quarantined_records += sum(1 for i in items if i.quality in (DataQuality.quarantined, DataQuality.invalid))
        job.duplicate_records += sum(1 for i in items if i.duplicate)
        cp = await s.get(IngestionCheckpoint, job_id, with_for_update=True)
        assert cp is not None
        cp.last_record_index = max(cp.last_record_index, max(idx for idx, _ in batch))

    async def _write_canonical(self, s: AsyncSession, dataset_id: uuid.UUID, items: list[_Item]) -> None:
        if not items:
            return
        tx_rows: dict[str, dict[str, Any]] = {}
        for it in items:
            assert it.norm
            d = it.norm.data
            if d["txid"] in tx_rows:
                continue
            tx_rows[d["txid"]] = {
                "txid": d["txid"],
                "first_seen_at": _ts(d["timestamp"]),
                "block_height": d.get("block_height"),
                "block_hash": d.get("block_hash"),
                "confirmations": d.get("confirmations"),
                "version": d.get("version"),
                "locktime": d.get("locktime"),
                "size": d.get("size"),
                "vsize": d.get("vsize"),
                "weight": d.get("weight"),
                "total_input_sat": sum(d["input_amounts"]),
                "total_output_sat": sum(d["output_amounts"]),
                "fee_sat": d["fee"],
                "input_count": len(d["input_addresses"]),
                "output_count": len(d["output_addresses"]),
                "script_type": d.get("script_type"),
                "data_quality": it.quality,
                "content_hash": it.norm.tx_hash,
                "source_raw_record_id": it.raw_id,
                "dataset_id": dataset_id,
                "_norm": d,
            }
        new = await s.execute(
            pg_insert(Transaction)
            .values([{k: v for k, v in r.items() if k != "_norm"} for r in tx_rows.values()])
            .on_conflict_do_nothing(index_elements=["txid"])
            .returning(Transaction.id, Transaction.txid)
        )
        new_ids = {r.txid: r.id for r in new}
        # earlier-seen txs keep their earliest first_seen_at
        for txid in set(tx_rows) - set(new_ids):
            await s.execute(
                update(Transaction)
                .where(Transaction.txid == txid)
                .values(first_seen_at=func.least(Transaction.first_seen_at, tx_rows[txid]["first_seen_at"]))
            )
        ins_rows: list[dict[str, Any]] = []
        out_rows: list[dict[str, Any]] = []
        addr_seen: dict[str, list[datetime]] = {}
        for txid, tid in new_ids.items():
            d = tx_rows[txid]["_norm"]
            for side, rows in (("input", ins_rows), ("output", out_rows)):
                for pos, (a, amt) in enumerate(zip(d[f"{side}_addresses"], d[f"{side}_amounts"], strict=True)):
                    info = classify_address(a)
                    rows.append(
                        {
                            "transaction_id": tid,
                            "position": pos,
                            "address": a,
                            "amount_sat": amt,
                            "script_type": info.address_type if info else None,
                        }
                    )
        if ins_rows:
            await s.execute(pg_insert(TransactionInput).values(ins_rows).on_conflict_do_nothing())
        if out_rows:
            await s.execute(pg_insert(TransactionOutput).values(out_rows).on_conflict_do_nothing())

        ip_seen: dict[str, list[datetime]] = {}
        asn_seen: dict[int, list[datetime]] = {}
        geo_seen: dict[str, list[datetime]] = {}
        obs_rows = []
        all_txids = list(tx_rows)
        tid_map = {
            r.txid: r.id for r in await s.execute(select(Transaction.id, Transaction.txid).where(Transaction.txid.in_(all_txids)))
        }
        for it in items:
            assert it.norm
            d, t = it.norm.data, _ts(it.norm.data["timestamp"])
            for a in d["input_addresses"] + d["output_addresses"]:
                addr_seen.setdefault(a, []).append(t)
            for ip in (d["src_ip"], d["dst_ip"]):
                ip_seen.setdefault(ip, []).append(t)
            if d.get("asn") is not None:
                asn_seen.setdefault(d["asn"], []).append(t)
            if d.get("geo_country"):
                geo_seen.setdefault(d["geo_country"], []).append(t)
            obs_rows.append(
                {
                    "obs_hash": it.norm.obs_hash,
                    "txid": d["txid"],
                    "transaction_id": tid_map.get(d["txid"]),
                    "observed_at": t,
                    "src_ip": d["src_ip"],
                    "dst_ip": d["dst_ip"],
                    "src_port": d["src_port"],
                    "dst_port": d["dst_port"],
                    "protocol": d.get("protocol"),
                    "asn": d.get("asn"),
                    "geo_country": d.get("geo_country"),
                    "extra": d.get("extra") or {},
                    "data_quality": it.quality,
                    "source_raw_record_id": it.raw_id,
                    "dataset_id": dataset_id,
                }
            )
        await s.execute(pg_insert(NetworkObservation).values(obs_rows).on_conflict_do_nothing(index_elements=["obs_hash"]))

        if addr_seen:
            rows = []
            for a, ts in addr_seen.items():
                info = classify_address(a)
                rows.append(
                    {
                        "address": a,
                        "address_type": info.address_type if info else "unknown",
                        "network": info.network if info else "unknown",
                        "first_seen_at": min(ts),
                        "last_seen_at": max(ts),
                    }
                )
            st = pg_insert(Address).values(rows)
            await s.execute(
                st.on_conflict_do_update(
                    index_elements=["address"],
                    set_={
                        "first_seen_at": func.least(Address.first_seen_at, st.excluded.first_seen_at),
                        "last_seen_at": func.greatest(Address.last_seen_at, st.excluded.last_seen_at),
                    },
                )
            )
        if ip_seen:
            rows = [
                {
                    "ip": ip,
                    "version": ipaddress.ip_address(ip).version,
                    "is_private": ipaddress.ip_address(ip).is_private,
                    "first_seen_at": min(ts),
                    "last_seen_at": max(ts),
                }
                for ip, ts in ip_seen.items()
            ]
            st = pg_insert(IpEntity).values(rows)
            await s.execute(
                st.on_conflict_do_update(
                    index_elements=["ip"],
                    set_={
                        "first_seen_at": func.least(IpEntity.first_seen_at, st.excluded.first_seen_at),
                        "last_seen_at": func.greatest(IpEntity.last_seen_at, st.excluded.last_seen_at),
                    },
                )
            )
        for model, key, seen_map in ((AsnEntity, "asn", asn_seen), (GeoEntity, "country_code", geo_seen)):
            if seen_map:
                rows = [{key: k, "first_seen_at": min(ts), "last_seen_at": max(ts)} for k, ts in seen_map.items()]
                st = pg_insert(model).values(rows)
                await s.execute(
                    st.on_conflict_do_update(
                        index_elements=[key],
                        set_={
                            "first_seen_at": func.least(model.first_seen_at, st.excluded.first_seen_at),
                            "last_seen_at": func.greatest(model.last_seen_at, st.excluded.last_seen_at),
                        },
                    )
                )


def _jsonable(o: Any) -> Any:
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_jsonable(v) for v in o]
    if isinstance(o, str | int | float | bool) or o is None:
        return o
    return str(o)  # Decimal from ijson, datetimes etc.
