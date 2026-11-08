"""Derived-analytics stage: features -> correlation -> graph patterns/metrics -> clustering.

Derived tables are recomputed from canonical data on each run (idempotent). Canonical data and
evidence are never modified. Each run is recorded in analysis_runs.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analytics.features import ADDR_SCHEMA_VERSION, NET_SCHEMA_VERSION, SCHEMA_VERSION, compute_features
from app.analytics.loader import load_transactions
from app.core.logging import get_logger
from app.graph.clustering import LIMITS, behavioural_clusters, change_output_clusters, common_input_clusters
from app.graph.patterns import detect_patterns, graph_metrics
from app.intelligence.correlation import LIMITATION, correlate
from app.models import (
    AddressCluster,
    AddressFeature,
    AnalysisRun,
    ClusterMembership,
    CorrelationIndicator,
    GraphDetection,
    NetworkFeature,
    Transaction,
    TransactionFeature,
)

log = get_logger(__name__)
CHUNK = 2000


async def _bulk(s: AsyncSession, model: Any, rows: list[dict[str, Any]]) -> None:
    for i in range(0, len(rows), CHUNK):
        await s.execute(pg_insert(model).values(rows[i : i + CHUNK]))


async def run_analytics(sm: async_sessionmaker[AsyncSession], dataset_id: uuid.UUID | None = None) -> dict[str, Any]:
    run_id = uuid.uuid4().hex
    async with sm() as s, s.begin():
        s.add(AnalysisRun(id=run_id, stage="analytics", status="running", params={"trigger_dataset": str(dataset_id)}))
    async with sm() as s:
        txs = await load_transactions(s)
    fr = compute_features(txs)
    indicators = correlate(txs)
    detections = detect_patterns(txs)
    gm = graph_metrics(txs)
    ci, excluded = common_input_clusters(txs)
    co = change_output_clusters(txs)
    for a, f in fr.addresses.items():
        f["component_size"] = gm.component_size.get(a)
        f["betweenness"] = gm.betweenness.get(a)
        f["bipartite_degree"] = gm.degree.get(a)
    bc = behavioural_clusters(fr.addresses)
    clusters = ci + co + bc
    cluster_ids: dict[str, list[str]] = {}
    tx_ids = {t.txid: t.id for t in txs}

    async with sm() as s, s.begin():
        await s.execute(delete(TransactionFeature).where(TransactionFeature.schema_version == SCHEMA_VERSION))
        await s.execute(delete(AddressFeature).where(AddressFeature.schema_version == ADDR_SCHEMA_VERSION))
        await s.execute(delete(NetworkFeature).where(NetworkFeature.schema_version == NET_SCHEMA_VERSION))
        await s.execute(delete(CorrelationIndicator))
        await s.execute(delete(GraphDetection))
        await s.execute(delete(AddressCluster).where(AddressCluster.review_status == "unreviewed"))

        cluster_rows, member_rows = [], []
        for c in clusters:
            cid = uuid.uuid4()
            cluster_rows.append(
                {
                    "id": cid,
                    "method": c.method,
                    "confidence": c.confidence,
                    "size": len(c.members),
                    "evidence": c.evidence,
                    "limitations": LIMITS[c.method],
                    "run_id": run_id,
                }
            )
            for a, lc in c.members.items():
                member_rows.append(
                    {"cluster_id": cid, "address": a, "link_confidence": lc, "evidence_txids": c.evidence_txids.get(a, [])}
                )
                cluster_ids.setdefault(a, []).append(str(cid))
        await _bulk(s, AddressCluster, cluster_rows)
        await _bulk(s, ClusterMembership, member_rows)

        cutoff = fr.cutoff or datetime.now(UTC)
        await _bulk(
            s,
            TransactionFeature,
            [
                {
                    "transaction_id": tx_ids[txid],
                    "as_of": datetime.fromisoformat(f["_as_of"]),
                    "schema_version": SCHEMA_VERSION,
                    "features": {k: v for k, v in f.items() if not k.startswith("_")},
                }
                for txid, f in fr.tx.items()
            ],
        )
        await _bulk(
            s,
            AddressFeature,
            [
                {
                    "address": a,
                    "as_of": cutoff,
                    "schema_version": ADDR_SCHEMA_VERSION,
                    "features": {**f, "cluster_ids": cluster_ids.get(a, [])},
                }
                for a, f in fr.addresses.items()
            ],
        )
        await _bulk(
            s,
            NetworkFeature,
            [
                {"entity_type": et, "entity_key": k, "as_of": cutoff, "schema_version": NET_SCHEMA_VERSION, "features": f}
                for (et, k), f in fr.network.items()
            ],
        )
        await _bulk(
            s,
            CorrelationIndicator,
            [
                {
                    "indicator_type": i.indicator_type,
                    "entity_type": i.entity_type,
                    "entity_key": i.entity_key,
                    "window_start": i.window_start,
                    "window_end": i.window_end,
                    "strength": i.strength,
                    "confidence": i.confidence,
                    "metrics": i.metrics,
                    "evidence_refs": i.evidence_refs,
                    "limitations": LIMITATION,
                    "run_id": run_id,
                }
                for i in indicators
            ],
        )
        await _bulk(
            s,
            GraphDetection,
            [
                {
                    "pattern": d.pattern,
                    "anchor_txid": d.anchor_txid,
                    "txids": d.txids,
                    "addresses": d.addresses,
                    "metrics": d.metrics,
                    "confidence": d.confidence,
                    "explanation": d.explanation,
                    "limitations": d.limitations,
                    "window_start": d.window_start,
                    "window_end": d.window_end,
                    "run_id": run_id,
                }
                for d in detections
            ],
        )
        stats = {
            "transactions": len(txs),
            "addresses": len(fr.addresses),
            "indicators": len(indicators),
            "detections": len(detections),
            "clusters": len(clusters),
            "coinjoin_like_excluded_from_clustering": excluded,
        }
        run = await s.get(AnalysisRun, run_id)
        assert run is not None
        run.status, run.finished_at, run.stats = "completed", datetime.now(UTC), stats
    log.info("analytics_done", run_id=run_id, **stats)
    _ = Transaction
    return stats


async def analytics_stage(sm: async_sessionmaker[AsyncSession], dataset_id: uuid.UUID) -> None:
    await run_analytics(sm, dataset_id)
