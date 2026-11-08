"""Alert generation from actual detection results only (graph detections, correlation indicators,
model predictions and persisted risk assessments). Alerts are deduplicated per (category, entity).
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.alerts.rules import DEFAULT_RULES
from app.core.hashing import sha256_hex
from app.models import (
    AddressCluster,
    AddressFeature,
    Alert,
    AlertLink,
    AlertRule,
    AnomalyPrediction,
    ClusterMembership,
    CorrelationIndicator,
    GraphDetection,
    ModelVersion,
    NetworkObservation,
    RiskAssessment,
    Transaction,
    TransactionFeature,
    TransactionInput,
    TransactionOutput,
)
from app.models.base import Severity
from app.services.risk import band

UNCERTAINTY = (
    "Detections are heuristic and model-based on bulk metadata. Legitimate services (exchanges, payroll, wallet "
    "consolidation, privacy tools) can produce the same structures. An IP co-occurrence is not ownership."
)


@dataclass
class Candidate:
    rule: AlertRule
    entity_type: str
    entity_key: str
    title: str
    explanation: str
    severity: Severity
    confidence: float
    txid: str | None = None
    addresses: list[str] = field(default_factory=list)
    observation_ids: list[int] = field(default_factory=list)
    observed: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    method: str = "rule"


async def seed_rules(s: AsyncSession) -> None:
    existing = set((await s.execute(select(AlertRule.code))).scalars())
    for r in DEFAULT_RULES:
        if r["code"] not in existing:
            s.add(AlertRule(**r))
    await s.flush()


def _conf_label(c: float) -> str:
    return "high" if c >= 0.75 else "medium" if c >= 0.5 else "low"


async def generate(sm: async_sessionmaker[AsyncSession]) -> dict[str, int]:
    async with sm() as s, s.begin():
        await seed_rules(s)
    async with sm() as s:
        rules = {r.code: r for r in (await s.execute(select(AlertRule).where(AlertRule.enabled.is_(True)))).scalars()}
        risk = {
            (r.entity_type, r.entity_key): r
            for r in (await s.execute(select(RiskAssessment).where(RiskAssessment.is_current.is_(True)))).scalars()
        }
        mvs = {
            m.entity_type: m for m in (await s.execute(select(ModelVersion).where(ModelVersion.is_active.is_(True)))).scalars()
        }
        pred: dict[tuple[str, str], float] = {}
        for et, mv in mvs.items():
            for k, sc in await s.execute(
                select(AnomalyPrediction.entity_key, AnomalyPrediction.anomaly_score).where(
                    AnomalyPrediction.model_version_id == mv.id
                )
            ):
                pred[(et, k)] = sc
        dets = (await s.execute(select(GraphDetection))).scalars().all()
        inds = (await s.execute(select(CorrelationIndicator))).scalars().all()
        txrows = (await s.execute(select(Transaction.id, Transaction.txid, Transaction.total_output_sat))).all()
        tfeat = {r[0]: r[1] for r in await s.execute(select(TransactionFeature.transaction_id, TransactionFeature.features))}
        afeat = {r[0]: r[1] for r in await s.execute(select(AddressFeature.address, AddressFeature.features))}
        tx_addrs: dict[str, list[str]] = defaultdict(list)
        id2 = {t.id: t.txid for t in txrows}
        for tid, a in await s.execute(select(TransactionInput.transaction_id, TransactionInput.address)):
            tx_addrs[id2[tid]].append(a)
        for tid, a in await s.execute(select(TransactionOutput.transaction_id, TransactionOutput.address)):
            tx_addrs[id2[tid]].append(a)
        obs_ids: dict[str, list[int]] = defaultdict(list)
        for oid, txid in await s.execute(select(NetworkObservation.id, NetworkObservation.txid)):
            if len(obs_ids[txid]) < 10:
                obs_ids[txid].append(oid)
        clusters = (
            (await s.execute(select(AddressCluster).where(AddressCluster.method == "common_input", AddressCluster.size >= 3)))
            .scalars()
            .all()
        )
        members: dict[uuid.UUID, list[str]] = defaultdict(list)
        for cid, a in await s.execute(
            select(ClusterMembership.cluster_id, ClusterMembership.address).where(
                ClusterMembership.cluster_id.in_([c.id for c in clusters])
            )
        ):
            members[cid].append(a)

    def rs(et: str, k: str) -> int:
        r = risk.get((et, k))
        return r.score if r else 0

    def sev(et: str, k: str, floor: Severity = Severity.low) -> Severity:
        order = list(Severity)
        b = band(rs(et, k))
        return b if order.index(b) >= order.index(floor) else floor

    cands: list[Candidate] = []
    det_map = {
        "high_fan_out": "GRAPH_FAN_OUT",
        "high_fan_in": "GRAPH_FAN_IN",
        "peel_chain": "GRAPH_PEEL_CHAIN",
        "rapid_layering": "GRAPH_LAYERING",
        "circular_flow": "GRAPH_CYCLE",
    }
    for d in dets:
        code = det_map.get(d.pattern)
        rule = rules.get(code or "")
        if rule is None or d.anchor_txid is None:
            continue
        th = rule.thresholds
        anchor = d.anchor_txid
        if d.confidence < th.get("min_confidence", 0) or rs("transaction", anchor) < th.get("min_risk", 0):
            continue
        if d.metrics.get("hops", 99) < th.get("min_hops", 0):
            continue
        cands.append(
            Candidate(
                rule,
                "transaction",
                anchor,
                f"{d.pattern.replace('_', ' ').title()} anchored at {anchor[:12]}…",
                f"{d.explanation} Risk {rs('transaction', anchor)}/100. {d.limitations}",
                sev("transaction", anchor, Severity.moderate),
                d.confidence,
                anchor,
                d.addresses[:200],
                obs_ids.get(anchor, []),
                {"pattern": d.pattern, **d.metrics},
                {"graph_detection_id": d.id, "txids": d.txids[:100]},
                "graph_heuristic",
            )
        )
        if d.pattern == "high_fan_out" and "GRAPH_SPLITTING" in rules:
            r2 = rules["GRAPH_SPLITTING"]
            if (
                d.metrics.get("value_spread", 1) <= r2.thresholds["max_value_spread"]
                and rs("transaction", anchor) >= r2.thresholds["min_risk"]
            ):
                cands.append(
                    Candidate(
                        r2,
                        "transaction",
                        anchor,
                        f"Value splitting into {d.metrics['outputs']} near-equal outputs",
                        f"Outputs differ by at most {d.metrics['value_spread']:.2%} of the largest value. {d.limitations}",
                        sev("transaction", anchor, Severity.moderate),
                        d.confidence,
                        anchor,
                        d.addresses[:200],
                        obs_ids.get(anchor, []),
                        {"value_spread": d.metrics["value_spread"]},
                        {"graph_detection_id": d.id},
                        "graph_heuristic",
                    )
                )
        if d.pattern == "high_fan_in" and "GRAPH_CONSOLIDATION" in rules:
            r3 = rules["GRAPH_CONSOLIDATION"]
            sc = pred.get(("transaction", anchor), 0)
            if sc >= r3.thresholds["min_anomaly_score"] and rs("transaction", anchor) >= r3.thresholds["min_risk"]:
                cands.append(
                    Candidate(
                        r3,
                        "transaction",
                        anchor,
                        "Unusual consolidation (fan-in + model outlier)",
                        f"{d.explanation} Model outlier rank {sc:.3f}.",
                        sev("transaction", anchor, Severity.moderate),
                        min(d.confidence, sc),
                        anchor,
                        d.addresses[:200],
                        obs_ids.get(anchor, []),
                        {"anomaly_score": sc},
                        {"graph_detection_id": d.id},
                        "graph_heuristic+ml",
                    )
                )

    if "NET_IP_BURST" in rules:
        r = rules["NET_IP_BURST"]
        for i in inds:
            if i.indicator_type != "ip_transaction_burst":
                continue
            if (
                i.confidence < r.thresholds["min_confidence"]
                or i.metrics.get("ratio_to_baseline", 0) < r.thresholds["min_ratio_to_baseline"]
            ):
                continue
            txs = i.evidence_refs.get("txids", [])
            top = max(txs, key=lambda t: rs("transaction", t), default=None)
            cands.append(
                Candidate(
                    r,
                    "ip",
                    i.entity_key,
                    f"{i.metrics['tx_in_window']} transactions first-observed from {i.entity_key} in "
                    f"{i.metrics['window_minutes']:.0f} min",
                    f"Source IP first-announced {i.metrics['tx_in_window']} transactions within "
                    f"{i.metrics['window_minutes']:.0f} minutes ({i.metrics['ratio_to_baseline']}x its baseline rate). {i.limitations}",
                    Severity.elevated if i.confidence >= 0.75 else Severity.moderate,
                    i.confidence,
                    top,
                    sorted({a for t in txs[:50] for a in tx_addrs.get(t, [])})[:200],
                    i.evidence_refs.get("observation_ids", [])[:200],
                    i.metrics,
                    {"correlation_indicator_id": i.id, "txids": txs[:200]},
                    "network_correlation",
                )
            )

    values = np.array([t.total_output_sat for t in txrows]) if txrows else np.array([0])
    for tid, txid, value in txrows:
        f = tfeat.get(tid, {})
        sc = pred.get(("transaction", txid), 0.0)
        risk_tx = rs("transaction", txid)
        if (
            (rule := rules.get("TX_HIGH_ANOMALY"))
            and sc >= rule.thresholds["min_anomaly_score"]
            and risk_tx >= rule.thresholds["min_risk"]
        ):
            ra = risk[("transaction", txid)]
            cands.append(
                Candidate(
                    rule,
                    "transaction",
                    txid,
                    f"Extreme model outlier {txid[:12]}…",
                    ra.explanation,
                    band(risk_tx),
                    sc,
                    txid,
                    tx_addrs.get(txid, [])[:200],
                    obs_ids.get(txid, []),
                    {"anomaly_score": sc, "risk": risk_tx},
                    {"risk_assessment_id": ra.id},
                    "isolation_forest",
                )
            )
        hold = f.get("min_input_holding_secs")
        if (
            (rule := rules.get("TX_RAPID_MOVEMENT"))
            and hold is not None
            and hold <= rule.thresholds["max_holding_secs"]
            and risk_tx >= rule.thresholds["min_risk"]
        ):
            cands.append(
                Candidate(
                    rule,
                    "transaction",
                    txid,
                    f"Rapid movement: inputs spent {hold:.0f}s after receipt",
                    f"Funds were re-spent {hold:.0f} seconds after arriving and the transaction scored {risk_tx}/100.",
                    band(risk_tx),
                    0.6,
                    txid,
                    tx_addrs.get(txid, [])[:200],
                    obs_ids.get(txid, []),
                    {"holding_secs": hold},
                )
            )
        if (
            (rule := rules.get("TX_UNUSUAL_AMOUNT"))
            and value >= np.percentile(values, rule.thresholds["value_percentile"])
            and sc >= rule.thresholds["min_anomaly_score"]
        ):
            cands.append(
                Candidate(
                    rule,
                    "transaction",
                    txid,
                    "Unusual transaction amount with outlier structure",
                    f"Value {value} sat is in the top {100 - rule.thresholds['value_percentile']:.1f}% and the model ranks it "
                    f"{sc:.3f}. Size alone is not suspicious.",
                    Severity.moderate,
                    sc,
                    txid,
                    tx_addrs.get(txid, [])[:200],
                    obs_ids.get(txid, []),
                    {"value_sat": value, "anomaly_score": sc},
                )
            )

    # Addresses already listed on a transaction/network alert are not re-alerted individually (avoids queue flooding);
    # they remain visible on that alert and on the address page.
    covered = {a for c in cands for a in c.addresses}
    for (et, key), ra in risk.items():
        if et != "address" or key in covered:
            continue
        sc = pred.get(("address", key), 0.0)
        if (
            (rule := rules.get("ADDR_UNUSUAL_BEHAVIOUR"))
            and ra.score >= rule.thresholds["min_risk"]
            and sc >= rule.thresholds["min_anomaly_score"]
        ):
            cands.append(
                Candidate(
                    rule,
                    "address",
                    key,
                    f"Unusual address behaviour {key[:12]}…",
                    ra.explanation,
                    band(ra.score),
                    sc,
                    None,
                    [key],
                    [],
                    {"risk": ra.score, "anomaly_score": sc},
                    {"risk_assessment_id": ra.id},
                    "isolation_forest",
                )
            )
        tpd = (afeat.get(key) or {}).get("tx_per_day") or 0
        n_tx = (afeat.get(key) or {}).get("tx_count") or 0
        if (
            (rule := rules.get("ADDR_UNUSUAL_FREQUENCY"))
            and tpd >= rule.thresholds["min_tx_per_day"]
            and n_tx >= rule.thresholds.get("min_tx_count", 0)
            and ra.score >= rule.thresholds["min_risk"]
        ):
            cands.append(
                Candidate(
                    rule,
                    "address",
                    key,
                    f"High activity rate ({tpd:.1f} tx/day)",
                    ra.explanation,
                    band(ra.score),
                    0.55,
                    None,
                    [key],
                    [],
                    {"tx_per_day": tpd},
                )
            )

    if rule := rules.get("CLUSTER_NEW_UNUSUAL"):
        for c in clusters:
            m = members[c.id]
            hot = [a for a in m if rs("address", a) >= 50]
            if len(m) >= rule.thresholds["min_size"] and len(hot) / len(m) >= rule.thresholds["min_elevated_share"]:
                cands.append(
                    Candidate(
                        rule,
                        "cluster",
                        str(c.id),
                        f"Common-input cluster of {len(m)} with {len(hot)} elevated members",
                        f"{len(hot)}/{len(m)} addresses in this probabilistic cluster are Elevated risk. {c.limitations}",
                        Severity.moderate,
                        min(c.confidence, 0.7),
                        None,
                        m[:200],
                        [],
                        {"size": len(m), "elevated": len(hot)},
                        {"cluster_id": str(c.id)},
                        "clustering_heuristic",
                    )
                )
    return await _persist(sm, cands, {et: mv.id for et, mv in mvs.items()}, risk)


async def _persist(
    sm: async_sessionmaker[AsyncSession],
    cands: list[Candidate],
    models: dict[str, uuid.UUID],
    risk: dict[tuple[str, str], RiskAssessment],
) -> dict[str, int]:
    stats = {"candidates": len(cands), "created": 0, "deduplicated": 0}
    async with sm() as s, s.begin():
        by_key: dict[str, Candidate] = {}
        for c in cands:
            k = sha256_hex(f"{c.rule.category}|{c.entity_type}|{c.entity_key}")
            if k not in by_key or c.confidence > by_key[k].confidence:
                by_key[k] = c
        existing = {a.dedup_key: a for a in (await s.execute(select(Alert).where(Alert.dedup_key.in_(list(by_key))))).scalars()}
        for k, c in by_key.items():
            trig = {"code": c.rule.code, "version": c.rule.version, "thresholds": c.rule.thresholds, "observed": c.observed}
            if k in existing:
                a = existing[k]
                if trig not in a.triggered_rules:
                    a.triggered_rules = [*a.triggered_rules, trig]
                a.occurrence_count += 1
                stats["deduplicated"] += 1
                continue
            ra = risk.get((c.entity_type, c.entity_key))
            s.add(
                Alert(
                    dedup_key=k,
                    category=c.rule.category,
                    severity=c.severity,
                    title=c.title[:255],
                    entity_type=c.entity_type,
                    entity_key=c.entity_key,
                    txid=c.txid,
                    addresses=c.addresses,
                    network_observation_ids=c.observation_ids,
                    risk_score=ra.score
                    if ra
                    else (risk.get(("transaction", c.txid)).score if c.txid and ("transaction", c.txid) in risk else None),  # type: ignore[union-attr]
                    risk_assessment_id=ra.id if ra else None,
                    detection_method=c.method,
                    triggered_rules=[trig],
                    model_version_id=models.get("transaction" if c.entity_type in ("transaction", "ip") else "address"),
                    evidence_refs=c.evidence,
                    explanation=c.explanation,
                    confidence=_conf_label(c.confidence),
                    uncertainty_notes=UNCERTAINTY,
                )
            )
            stats["created"] += 1
        await s.flush()
        # related-alert links: alerts sharing the anchor txid
        rows = (await s.execute(select(Alert.id, Alert.txid).where(Alert.txid.is_not(None)))).all()
        groups: dict[str, list[uuid.UUID]] = defaultdict(list)
        for aid, t in rows:
            groups[t].append(aid)
        links = [
            {"alert_id": a, "related_alert_id": b, "reason": f"same transaction {t[:16]}"}
            for t, ids in groups.items()
            if len(ids) > 1
            for a in ids
            for b in ids
            if a != b
        ]
        for i in range(0, len(links), 2000):
            await s.execute(pg_insert(AlertLink).values(links[i : i + 2000]).on_conflict_do_nothing())
    return stats


async def alert_stage(sm: async_sessionmaker[AsyncSession], dataset_id: uuid.UUID) -> None:
    await generate(sm)
