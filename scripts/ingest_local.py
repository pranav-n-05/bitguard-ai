#!/usr/bin/env python3
"""Offline bulk ingestion of local files (no HTTP upload).

Usage: backend/.venv/bin/python scripts/ingest_local.py --name "seed42" FILE [FILE ...]
Requires BITGUARD_DATABASE_URL (defaults to the dev compose database).
"""

import argparse
import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.database.session import get_sessionmaker  # noqa: E402
from app.ingestion.service import IngestionService  # noqa: E402
from app.models import Dataset  # noqa: E402
from app.services import audit, datasets  # noqa: E402
from app.services.bootstrap import seed_rbac  # noqa: E402
from app.services.pipeline import run_post_ingestion  # noqa: E402


async def main(a: argparse.Namespace) -> None:
    sm = get_sessionmaker()
    async with sm() as s, s.begin():
        await seed_rbac(s)
        ds = Dataset(name=a.name, provenance=a.provenance, description="Ingested via scripts/ingest_local.py")
        s.add(ds)
        await s.flush()
        await audit.record(s, "dataset.created", "dataset", str(ds.id), details={"name": a.name, "via": "cli"})
        for f in a.files:
            await datasets.register_local_file(s, ds, Path(f), None)
        jobs = await datasets.create_jobs(s, ds.id, None)
        job_ids = [j.id for j in jobs]
        ds_id = ds.id
    for jid in job_ids:
        t0 = time.perf_counter()
        job = await IngestionService(sm).run(jid)
        dt = time.perf_counter() - t0
        print(
            f"job {jid}: {job.status.value} processed={job.processed_records} valid={job.valid_records} "
            f"partial={job.partial_records} quarantined={job.quarantined_records} duplicates={job.duplicate_records} "
            f"in {dt:.1f}s ({job.processed_records / dt:.0f} rec/s)"
        )
    await run_post_ingestion(sm, ds_id)
    print(f"dataset {ds_id} processed")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--name", required=True)
    p.add_argument("--provenance", default="synthetic", choices=["synthetic", "historical", "external"])
    p.add_argument("files", nargs="+")
    asyncio.run(main(p.parse_args()))
