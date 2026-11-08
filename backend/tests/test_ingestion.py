"""Integration tests for the ingestion engine (SYNTHETIC data, real Postgres)."""

import json
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.database.session import get_sessionmaker
from app.ingestion.service import IngestionService
from app.models import (
    Address,
    IngestionError,
    IngestionJob,
    NetworkObservation,
    RawRecord,
    Transaction,
    TransactionInput,
    TransactionOutput,
)
from app.models.base import JobStatus
from app.services import audit
from tests.conftest import auth_headers


async def _upload(client: AsyncClient, headers: dict[str, str], path: Path, **form: str) -> dict:  # type: ignore[type-arg]
    with path.open("rb") as f:
        r = await client.post(
            "/api/v1/ingestion/datasets",
            headers=headers,
            data={"name": form.pop("name", "synthetic test"), **form},
            files={"files": (path.name, f)},
        )
    assert r.status_code == 201, r.text
    return r.json()


async def _process(client: AsyncClient, headers: dict[str, str], dataset_id: str) -> list[dict]:  # type: ignore[type-arg]
    r = await client.post(f"/api/v1/ingestion/datasets/{dataset_id}/process", headers=headers)
    assert r.status_code == 202, r.text
    return r.json()


def _expected(path: Path) -> dict:  # type: ignore[type-arg]
    return json.loads(path.with_name("synthetic_small.labels.json").read_text())


@pytest.mark.parametrize("fmt", ["csv", "json", "jsonl", "xml"])
async def test_ingest_each_format(
    client: AsyncClient, admin: dict[str, str], small_dataset: dict[str, Path], session, fmt: str
) -> None:  # type: ignore[no-untyped-def]
    ds = await _upload(client, admin, small_dataset[fmt])
    assert ds["files"][0]["detected_format"] == fmt
    [job] = await _process(client, admin, ds["id"])
    labels = _expected(small_dataset[fmt])
    total = labels["meta"]["rows"]
    assert job["status"] == "completed_with_errors"
    assert job["processed_records"] == total
    assert job["quarantined_records"] == labels["injected_errors"]
    # Duplicates: injected exact duplicates + duplicate corruptions of the same row
    assert job["duplicate_records"] >= labels["injected_duplicates"]
    assert job["valid_records"] + job["partial_records"] + job["quarantined_records"] + job["duplicate_records"] == total
    # No silent loss: every source record is staged exactly once
    assert await session.scalar(select(func.count()).select_from(RawRecord)) == total
    # Canonical: every valid unique txid present exactly once with inputs/outputs
    n_tx = await session.scalar(select(func.count()).select_from(Transaction))
    expected_txids = labels["meta"]["unique_txids"]
    corrupted_txid = await session.scalar(
        select(func.count()).select_from(IngestionError).where(IngestionError.error_code == "invalid_txid")
    )
    assert n_tx == expected_txids - corrupted_txid
    fees_ok = await session.scalar(
        text("SELECT bool_and(t.total_input_sat - t.total_output_sat = t.fee_sat) FROM transactions t")
    )
    assert fees_ok
    sums_ok = await session.scalar(
        text(
            "SELECT bool_and(i.s = t.total_input_sat) FROM transactions t JOIN "
            "(SELECT transaction_id, sum(amount_sat) s FROM transaction_inputs GROUP BY 1) i ON i.transaction_id = t.id"
        )
    )
    assert sums_ok
    assert await session.scalar(select(func.count()).select_from(NetworkObservation)) > n_tx
    assert await session.scalar(select(func.count()).select_from(Address)) > 0


async def test_quarantine_reasons_recorded(client: AsyncClient, admin: dict[str, str], small_dataset: dict[str, Path]) -> None:
    ds = await _upload(client, admin, small_dataset["jsonl"])
    [job] = await _process(client, admin, ds["id"])
    r = await client.get(
        "/api/v1/ingestion/errors", headers=admin, params={"job_id": job["id"], "severity": "error", "limit": 500}
    )
    assert r.status_code == 200
    body = r.json()
    codes = {e["error_code"] for e in body["items"]}
    assert codes & {
        "invalid_txid",
        "invalid_ip",
        "fee_mismatch",
        "invalid_port",
        "invalid_timestamp",
        "invalid_address",
        "length_mismatch",
    }
    assert all(e["record_index"] is not None and e["message"] for e in body["items"])
    quarantined_indices = {e["record_index"] for e in body["items"]}
    assert len(quarantined_indices) == job["quarantined_records"]


async def test_reupload_same_file_rejected(client: AsyncClient, admin: dict[str, str], small_dataset: dict[str, Path]) -> None:
    ds = await _upload(client, admin, small_dataset["csv"])
    with small_dataset["csv"].open("rb") as f:
        r = await client.post(
            "/api/v1/ingestion/datasets",
            headers=admin,
            data={"name": "x", "dataset_id": ds["id"]},
            files={"files": ("again.csv", f)},
        )
    assert r.status_code == 409
    assert r.headers["content-type"].startswith("application/problem+json")


async def test_same_data_other_format_creates_no_duplicate_entities(
    client: AsyncClient, admin: dict[str, str], small_dataset: dict[str, Path], session
) -> None:  # type: ignore[no-untyped-def]
    ds1 = await _upload(client, admin, small_dataset["csv"])
    await _process(client, admin, ds1["id"])
    counts = [
        await session.scalar(select(func.count()).select_from(m))
        for m in (Transaction, TransactionInput, TransactionOutput, NetworkObservation, Address)
    ]
    ds2 = await _upload(client, admin, small_dataset["xml"], name="same data as xml")
    [job2] = await _process(client, admin, ds2["id"])
    assert job2["processed_records"] > 0
    session.expire_all()
    again = [
        await session.scalar(select(func.count()).select_from(m))
        for m in (Transaction, TransactionInput, TransactionOutput, NetworkObservation, Address)
    ]
    assert again == counts


async def test_process_is_idempotent(client: AsyncClient, admin: dict[str, str], small_dataset: dict[str, Path]) -> None:
    ds = await _upload(client, admin, small_dataset["jsonl"])
    await _process(client, admin, ds["id"])
    assert await _process(client, admin, ds["id"]) == []  # nothing left to do


async def test_resume_after_interruption(
    client: AsyncClient, admin: dict[str, str], small_dataset: dict[str, Path], session
) -> None:  # type: ignore[no-untyped-def]
    ds = await _upload(client, admin, small_dataset["jsonl"])
    from app.services.datasets import create_jobs

    [job] = await create_jobs(session, __import__("uuid").UUID(ds["id"]), None)
    await session.commit()
    job_id = job.id
    total = _expected(small_dataset["jsonl"])["meta"]["rows"]

    def crash(start: int) -> None:
        if start >= 100:
            raise RuntimeError("simulated worker crash")

    with pytest.raises(RuntimeError):
        await IngestionService(get_sessionmaker(), batch_size=50, fail_hook=crash).run(job_id)
    session.expire_all()
    j = await session.get(IngestionJob, job_id)
    assert j.status == JobStatus.failed and j.processed_records == 100
    assert await session.scalar(select(func.count()).select_from(RawRecord)) == 100

    done = await IngestionService(get_sessionmaker(), batch_size=50).run(job_id)
    assert done.attempts == 2 and done.processed_records == total
    assert await session.scalar(select(func.count()).select_from(RawRecord)) == total
    idx = (await session.execute(select(RawRecord.record_index).order_by(RawRecord.record_index))).scalars().all()
    assert idx == list(range(total))  # no gaps, no duplicates


async def test_file_integrity_checked(
    client: AsyncClient, admin: dict[str, str], small_dataset: dict[str, Path], session
) -> None:  # type: ignore[no-untyped-def]
    ds = await _upload(client, admin, small_dataset["jsonl"])
    stored = Path(ds["files"][0]["sha256"])
    from app.models import DatasetFile

    df = await session.get(DatasetFile, __import__("uuid").UUID(ds["files"][0]["id"]))
    with open(df.storage_path, "a") as f:
        f.write("tampered\n")
    r = await client.post(f"/api/v1/ingestion/datasets/{ds['id']}/process", headers=admin)
    assert r.status_code == 202 and r.json()[0]["status"] == "failed"
    session.expire_all()
    job = (await session.execute(select(IngestionJob))).scalar_one()
    assert job.status == JobStatus.failed and "integrity" in (job.error_message or "")
    assert stored


async def test_raw_records_and_audit_are_append_only(
    client: AsyncClient, admin: dict[str, str], small_dataset: dict[str, Path], session
) -> None:  # type: ignore[no-untyped-def]
    ds = await _upload(client, admin, small_dataset["jsonl"])
    await _process(client, admin, ds["id"])
    for stmt in (
        "UPDATE raw_records SET payload='{}' WHERE id=1",
        "DELETE FROM raw_records WHERE id=1",
        "UPDATE audit_logs SET action='x' WHERE seq=1",
    ):
        with pytest.raises(DBAPIError, match="append-only"):
            await session.execute(text(stmt))
        await session.rollback()
    ok, n, bad = await audit.verify_chain(session)
    assert ok and n >= 3 and bad is None


async def test_viewer_cannot_upload_or_process(
    client: AsyncClient, small_dataset: dict[str, Path], admin: dict[str, str]
) -> None:
    viewer = await auth_headers(client, "viewer")
    with small_dataset["csv"].open("rb") as f:
        r = await client.post("/api/v1/ingestion/datasets", headers=viewer, data={"name": "x"}, files={"files": ("a.csv", f)})
    assert r.status_code == 403
    ds = await _upload(client, admin, small_dataset["csv"])
    analyst = await auth_headers(client, "analyst")
    r = await client.post(f"/api/v1/ingestion/datasets/{ds['id']}/process", headers=analyst)
    assert r.status_code == 403
    r = await client.get("/api/v1/ingestion/datasets", headers=viewer)
    assert r.status_code == 200 and r.json()["total"] == 1


async def test_unsupported_extension(client: AsyncClient, admin: dict[str, str], tmp_path: Path) -> None:
    p = tmp_path / "evil.exe"
    p.write_bytes(b"MZ")
    with p.open("rb") as f:
        r = await client.post(
            "/api/v1/ingestion/datasets", headers=admin, data={"name": "x"}, files={"files": ("../../evil.exe", f)}
        )
    assert r.status_code == 400
