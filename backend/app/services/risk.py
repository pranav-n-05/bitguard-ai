"""Transparent, configurable 0-100 risk scoring.

score = 100 * sum(w_i * n_i) / sum(w_i over AVAILABLE components)

- Each component n_i is normalised to [0, 1] and stored with its rationale.
- Unavailable components are excluded from the denominator and raise the uncertainty indicator (never
  treated as zero risk or as maximum risk).
- Anti-double-counting: the ML anomaly and graph-structure components often react to the same
  structure (e.g. fan-out). They are combined as max + 0.5*min into one "structure" block.
- Value/size alone cannot exceed the Moderate band; CoinJoin-like privacy structures are capped at
  Moderate and halved.
Bands are prioritisation tiers, not probabilities of criminal conduct.
"""

import math
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ml.engine import VALUE_FEATURES
from app.models import (
    Alert,
    AnomalyPrediction,
    CorrelationIndicator,
    GraphDetection,
    ModelVersion,
    RiskAssessment,
    RiskComponent,
    SystemConfig,
    Transaction,
    TransactionFeature,
)
from app.models.base import AlertStatus, DataQuality, Severity

RULE_VERSION = "risk-v1.0"
DEFAULT_WEIGHTS: dict[str, float] = {
    "anomaly": 0.30,
    "graph": 0.25,
    "network": 0.15,
    "velocity": 0.10,
    "behavioural_deviation": 0.10,
    "history": 0.10,
}
LIMITATIONS = (
    "Risk scores prioritise investigative attention. They are derived from synthetic/historical bulk data, heuristics "
    "and unsupervised models, and are not evidence of criminal activity, identity, or ownership."
)
ACTIONS = {
    Severity.low: "No action required; retain for context.",
    Severity.moderate: "Review if linked to other leads; no escalation on this score alone.",
    Severity.elevated: "Analyst review recommended: verify the cited structural/network evidence and counterparties.",
    Severity.high: "Prioritise for analyst review; consider opening or linking an investigation after verifying evidence.",
}


def band(score: int) -> Severity:
    return (
        Severity.high if score >= 75 else Severity.elevated if score >= 50 else Severity.moderate if score >= 25 else Severity.low
    )


@dataclass
class Component:
    name: str
    normalised: float
    weight: float
    rationale: str
    raw: float | None = None
    available: bool = True


@dataclass
class Assessment:
    entity_type: str
    entity_key: str
    score: int
    band: Severity
    uncertainty: float
    components: list[Component]
    explanation: str
    evidence_refs: dict[str, Any]
    caps: list[str] = field(default_factory=list)


def combine(
    entity_type: str,
    key: str,
    comps: list[Component],
    *,
    value_only_anomaly: bool,
    coinjoin: bool,
    model_disagreement: float | None,
    quality: DataQuality,
    evidence: dict[str, Any],
) -> Assessment:
    by = {c.name: c for c in comps}
    avail = [c for c in comps if c.available]
    denom = sum(c.weight for c in avail)
    a, g = by.get("anomaly"), by.get("graph")
    struct = 0.0
    used: set[str] = set()
    if a and g and a.available and g.available:
        hi, lo = max(a.normalised, g.normalised), min(a.normalised, g.normalised)
        struct = (hi + 0.5 * lo) / 1.5 * (a.weight + g.weight)
        used = {"anomaly", "graph"}
    num = struct + sum(c.weight * c.normalised for c in avail if c.name not in used)
    raw_score = 100 * num / denom if denom else 0.0
    caps = []
    structural_evidence = any(by[n].available and by[n].normalised > 0.2 for n in ("graph", "network", "velocity") if n in by)
    if value_only_anomaly and not structural_evidence and raw_score > 49:
        raw_score, caps = 49.0, ["value/size-only anomaly capped below Elevated"]
    if coinjoin:
        raw_score = min(raw_score * 0.5, 49.0)
        caps.append("CoinJoin-like privacy structure: halved and capped at Moderate (privacy is not evidence of wrongdoing)")
    if quality == DataQuality.partial:
        caps.append("partial data quality")
    score = int(round(max(0.0, min(100.0, raw_score))))
    total_w = sum(c.weight for c in comps)
    uncertainty = 1 - (denom / total_w if total_w else 0)
    if model_disagreement is not None:
        uncertainty = min(1.0, uncertainty + 0.5 * model_disagreement)
    if quality == DataQuality.partial:
        uncertainty = min(1.0, uncertainty + 0.1)
    b = band(score)
    top = sorted((c for c in avail if c.normalised > 0), key=lambda c: -c.weight * c.normalised)[:3]
    parts = [f"{c.name.replace('_', ' ')} ({c.rationale})" for c in top]
    expl = (
        f"{entity_type.title()} scored {score}/100 ({b.value} observed risk). "
        + ("Main drivers: " + "; ".join(parts) + ". " if parts else "No component showed notable deviation. ")
        + (" ".join(caps) + ". " if caps else "")
        + f"Uncertainty {uncertainty:.2f} (share of unavailable evidence and model disagreement). "
        "This is an investigative lead, not evidence of criminal activity."
    )
    return Assessment(entity_type, key, score, b, round(uncertainty, 3), comps, expl, evidence, caps)


def _velocity(holding: float | None) -> Component:
    if holding is None:
        return Component("velocity", 0, DEFAULT_WEIGHTS["velocity"], "no prior funding observed for inputs", None, False)
    n = 1.0 if holding <= 60 else 0.0 if holding >= 86400 else 1 - math.log(holding / 60) / math.log(1440)
    return Component(
        "velocity", round(n, 4), DEFAULT_WEIGHTS["velocity"], f"inputs held {holding:.0f}s before being spent", holding
    )


async def weights(s: AsyncSession) -> dict[str, float]:
    row = (await s.execute(select(SystemConfig).where(SystemConfig.key == "risk_weights"))).scalar_one_or_none()
    return {**DEFAULT_WEIGHTS, **(row.value if row else {})}


def _anomaly(pred: Any, w: float) -> tuple[Component, bool]:
    if pred is None:
        return Component("anomaly", 0, w, "no model prediction available", None, False), False
    n = max(0.0, (pred.anomaly_score - 0.5) / 0.5) ** 2
    top = [c["feature"] for c in pred.contributions[:3]]
    value_only = bool(top) and all(t in VALUE_FEATURES for t in top)
    return Component(
        "anomaly",
        round(n, 4),
        w,
        f"outlier rank {pred.anomaly_score:.3f}; top features: {', '.join(top) or 'n/a'}",
        pred.anomaly_score,
    ), value_only


async def assess_all(sm: async_sessionmaker[AsyncSession]) -> dict[str, int]:
    async with sm() as s:
        w = await weights(s)
        mvs = {
            m.entity_type: m for m in (await s.execute(select(ModelVersion).where(ModelVersion.is_active.is_(True)))).scalars()
        }
        preds: dict[tuple[str, str], Any] = {}
        for et, mv in mvs.items():
            for p in (await s.execute(select(AnomalyPrediction).where(AnomalyPrediction.model_version_id == mv.id))).scalars():
                preds[(et, p.entity_key)] = p
        lof: dict[tuple[str, str], float] = {}
        for et in ("transaction", "address"):
            alt = (
                (
                    await s.execute(
                        select(ModelVersion)
                        .where(ModelVersion.entity_type == et, ModelVersion.is_active.is_(False))
                        .order_by(ModelVersion.trained_at.desc())
                    )
                )
                .scalars()
                .first()
            )
            if alt:
                for k, sc in await s.execute(
                    select(AnomalyPrediction.entity_key, AnomalyPrediction.anomaly_score).where(
                        AnomalyPrediction.model_version_id == alt.id
                    )
                ):
                    lof[(et, k)] = sc
        det_tx: dict[str, list[GraphDetection]] = defaultdict(list)
        det_addr: dict[str, list[GraphDetection]] = defaultdict(list)
        for d in (await s.execute(select(GraphDetection))).scalars():
            for t in d.txids:
                det_tx[t].append(d)
            for a in d.addresses:
                det_addr[a].append(d)
        ind_tx: dict[str, list[CorrelationIndicator]] = defaultdict(list)
        ind_addr: dict[str, list[CorrelationIndicator]] = defaultdict(list)
        for i in (await s.execute(select(CorrelationIndicator))).scalars():
            for t in i.evidence_refs.get("txids", []):
                ind_tx[t].append(i)
            if i.entity_type == "address":
                ind_addr[i.entity_key].append(i)
        txs = (await s.execute(select(Transaction.id, Transaction.txid, Transaction.data_quality))).all()
        feats = {r[0]: r[1] for r in await s.execute(select(TransactionFeature.transaction_id, TransactionFeature.features))}
        io_addr: dict[str, list[str]] = defaultdict(list)
        from app.models import TransactionInput

        id2txid = {t.id: t.txid for t in txs}
        for tid, a in await s.execute(select(TransactionInput.transaction_id, TransactionInput.address)):
            io_addr[id2txid[tid]].append(a)
        # History excludes false positives and the entity's own alerts (prevents self-reinforcing feedback).
        alert_rows = (
            await s.execute(
                select(Alert.txid, Alert.entity_key, Alert.addresses).where(Alert.status != AlertStatus.false_positive)
            )
        ).all()
        prior_alerts: dict[str, list[tuple[str | None, str]]] = defaultdict(list)
        for a_txid, a_key, addrs in alert_rows:
            for a in addrs:
                prior_alerts[a].append((a_txid, a_key))

    out: list[Assessment] = []
    for tid, txid, q in txs:
        f = feats.get(tid, {})
        pred = preds.get(("transaction", txid))
        anomaly, value_only = _anomaly(pred, w["anomaly"])
        ds = det_tx.get(txid, [])
        graph = (
            Component(
                "graph", round(max(d.confidence for d in ds), 4), w["graph"], "; ".join(sorted({d.pattern for d in ds})), len(ds)
            )
            if ds
            else Component("graph", 0.0, w["graph"], "no structural pattern detected")
        )
        inds = ind_tx.get(txid, [])
        strong = [i for i in inds if i.indicator_type != "repeated_address_ip_cooccurrence"]
        net_n = max((i.confidence * max(i.strength, 0.5) for i in strong), default=0.0)
        net_n = max(net_n, 0.3 * max((i.confidence for i in inds if i not in strong), default=0.0))
        network = (
            Component(
                "network", round(net_n, 4), w["network"], ", ".join(sorted({i.indicator_type for i in inds})) or "none", len(inds)
            )
            if f.get("network_observation_count") is not None
            else Component("network", 0, w["network"], "no network observations", None, False)
        )
        vel = _velocity(f.get("min_input_holding_secs"))
        vel.weight = w["velocity"]
        addr_scores = [preds[("address", a)].anomaly_score for a in io_addr.get(txid, []) if ("address", a) in preds]
        beh = (
            Component(
                "behavioural_deviation",
                round(max(0.0, (max(addr_scores) - 0.5) / 0.5) ** 2, 4),
                w["behavioural_deviation"],
                f"max input-address outlier rank {max(addr_scores):.3f}",
                max(addr_scores),
            )
            if addr_scores
            else Component("behavioural_deviation", 0, w["behavioural_deviation"], "no address model prediction", None, False)
        )
        n_prior = len({(t, k) for a in io_addr.get(txid, []) for t, k in prior_alerts.get(a, []) if t != txid and k != txid})
        hist = Component(
            "history", round(min(n_prior / 3, 1.0), 4), w["history"], f"{n_prior} prior alert(s) on input addresses", n_prior
        )
        dis = abs(pred.anomaly_score - lof[("transaction", txid)]) if pred and ("transaction", txid) in lof else None
        out.append(
            combine(
                "transaction",
                txid,
                [anomaly, graph, network, vel, beh, hist],
                value_only_anomaly=value_only,
                coinjoin=bool(f.get("is_coinjoin_like")),
                model_disagreement=dis,
                quality=q,
                evidence={
                    "graph_detection_ids": [d.id for d in ds],
                    "correlation_indicator_ids": [i.id for i in inds],
                    "prediction_id": pred.id if pred else None,
                    "transaction_id": tid,
                },
            )
        )

    addrs = {k for (et, k) in preds if et == "address"} | set(det_addr) | set(ind_addr)

    def det_txids_for(a: str) -> set[str]:
        return {t for d in det_addr.get(a, []) for t in d.txids}

    for a in addrs:
        pred = preds.get(("address", a))
        anomaly, value_only = _anomaly(pred, w["anomaly"])
        ds = det_addr.get(a, [])
        graph = (
            Component(
                "graph", round(max(d.confidence for d in ds), 4), w["graph"], "; ".join(sorted({d.pattern for d in ds})), len(ds)
            )
            if ds
            else Component("graph", 0.0, w["graph"], "no structural pattern detected")
        )
        inds = ind_addr.get(a, [])
        network = Component(
            "network",
            round(min(max((i.confidence for i in inds), default=0.0), 0.6), 4),
            w["network"],
            f"{len(inds)} network co-occurrence indicator(s)",
            len(inds),
        )
        n_hist = len({(t, k) for t, k in prior_alerts.get(a, []) if k != a and not (t and t in det_txids_for(a))})
        hist = Component(
            "history", round(min(n_hist / 3, 1.0), 4), w["history"], f"{n_hist} prior alert(s) on related activity", n_hist
        )
        dis = abs(pred.anomaly_score - lof[("address", a)]) if pred and ("address", a) in lof else None
        out.append(
            combine(
                "address",
                a,
                [anomaly, graph, network, hist],
                value_only_anomaly=value_only,
                coinjoin=False,
                model_disagreement=dis,
                quality=DataQuality.valid,
                evidence={
                    "graph_detection_ids": [d.id for d in ds],
                    "correlation_indicator_ids": [i.id for i in inds],
                    "prediction_id": pred.id if pred else None,
                },
            )
        )
    model_ids = {et: mv.id for et, mv in mvs.items()}
    return await persist(sm, out, w, model_ids)


async def persist(
    sm: async_sessionmaker[AsyncSession], items: list[Assessment], w: dict[str, float], model_ids: dict[str, uuid.UUID]
) -> dict[str, int]:
    stats = {"created": 0, "unchanged": 0, "superseded": 0}
    async with sm() as s, s.begin():
        current = {
            (r.entity_type, r.entity_key): r
            for r in (await s.execute(select(RiskAssessment).where(RiskAssessment.is_current.is_(True)))).scalars()
        }
        prev_comps: dict[int, dict[str, float]] = defaultdict(dict)
        if current:
            for aid, name, n in await s.execute(
                select(RiskComponent.assessment_id, RiskComponent.component, RiskComponent.normalised).where(
                    RiskComponent.assessment_id.in_([r.id for r in current.values()])
                )
            ):
                prev_comps[aid][name] = n
        new_rows = []
        for it in items:
            old = current.get((it.entity_type, it.entity_key))
            comp_now = {c.name: c.normalised for c in it.components}
            if old and old.score == it.score and prev_comps.get(old.id) == comp_now and old.rule_version == RULE_VERSION:
                stats["unchanged"] += 1
                continue
            reason = None
            if old:
                diffs = [
                    f"{k}: {prev_comps[old.id].get(k, 0):.2f}->{v:.2f}"
                    for k, v in comp_now.items()
                    if abs(prev_comps[old.id].get(k, 0) - v) > 1e-6
                ]
                reason = f"score {old.score}->{it.score}; " + (
                    "; ".join(diffs) or f"rule version {old.rule_version}->{RULE_VERSION}"
                )
                stats["superseded"] += 1
            new_rows.append((it, old, reason))
        if new_rows:
            ids_to_retire = [old.id for _, old, _ in new_rows if old]
            for i in range(0, len(ids_to_retire), 5000):
                await s.execute(
                    update(RiskAssessment).where(RiskAssessment.id.in_(ids_to_retire[i : i + 5000])).values(is_current=False)
                )
            for it, old, reason in new_rows:
                ra = RiskAssessment(
                    entity_type=it.entity_type,
                    entity_key=it.entity_key,
                    score=it.score,
                    band=it.band,
                    uncertainty=it.uncertainty,
                    rule_version=RULE_VERSION,
                    weights=w,
                    model_version_id=model_ids.get(it.entity_type),
                    explanation=it.explanation,
                    limitations=LIMITATIONS,
                    evidence_refs={**it.evidence_refs, "caps": it.caps},
                    recommended_action=ACTIONS[it.band],
                    is_current=True,
                    supersedes_id=old.id if old else None,
                    change_reason=reason,
                )
                s.add(ra)
                await s.flush()
                denom = sum(c.weight for c in it.components if c.available) or 1
                s.add_all(
                    [
                        RiskComponent(
                            assessment_id=ra.id,
                            component=c.name,
                            raw_value=c.raw,
                            normalised=c.normalised,
                            weight=c.weight,
                            contribution=round(100 * c.weight * c.normalised / denom, 3) if c.available else 0,
                            rationale=c.rationale,
                            available=c.available,
                        )
                        for c in it.components
                    ]
                )
                stats["created"] += 1
    return stats


async def risk_stage(sm: async_sessionmaker[AsyncSession], dataset_id: uuid.UUID) -> None:
    await assess_all(sm)


_ = datetime
