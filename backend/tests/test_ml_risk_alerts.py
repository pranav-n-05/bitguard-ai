"""ML reproducibility, risk scoring rules, alert generation and workflow (SYNTHETIC data)."""

import json
from pathlib import Path

import numpy as np
from httpx import AsyncClient
from sqlalchemy import func, select

from app.alerts.engine import generate
from app.database.session import get_sessionmaker
from app.ml import engine
from app.models import Alert, AuditLog, EvaluationLabel, RiskAssessment, SystemConfig
from app.models.base import DataQuality
from app.services.risk import Component, assess_all, band, combine
from tests.conftest import auth_headers


def test_isolation_forest_reproducible() -> None:
    rng = np.random.default_rng(0)
    x = rng.normal(size=(400, len(engine.TX_FEATURES)))
    x[::17, 3] = np.nan
    a = engine.fit("isolation_forest", "transaction", x, seed=7)
    b = engine.fit("isolation_forest", "transaction", x, seed=7)
    np.testing.assert_array_equal(a.raw_anomaly(x), b.raw_anomaly(x))
    s = a.anomaly_score(a.raw_anomaly(x))
    assert s.min() >= 0 and s.max() <= 1
    assert any(n.startswith("missing:") for n in a.feature_names)


def test_evaluation_metrics_honest_without_labels() -> None:
    m = engine.evaluate(np.array([0.1, 0.5, 0.9]), np.array([False, False, True]), None)
    assert m["labelled"] is False and "pr_auc" not in m


def _c(name: str, n: float, w: float, available: bool = True) -> Component:
    return Component(name, n, w, "test", None, available)


def test_score_bounds_and_bands() -> None:
    hi = combine(
        "transaction",
        "x",
        [_c("anomaly", 1, 0.3), _c("graph", 1, 0.25), _c("network", 1, 0.15)],
        value_only_anomaly=False,
        coinjoin=False,
        model_disagreement=0,
        quality=DataQuality.valid,
        evidence={},
    )
    lo = combine(
        "transaction",
        "y",
        [_c("anomaly", 0, 0.3), _c("graph", 0, 0.25)],
        value_only_anomaly=False,
        coinjoin=False,
        model_disagreement=None,
        quality=DataQuality.valid,
        evidence={},
    )
    assert hi.score == 100 and hi.band.value == "high" and lo.score == 0 and lo.band.value == "low"
    assert [band(s).value for s in (0, 24, 25, 49, 50, 74, 75, 100)] == [
        "low",
        "low",
        "moderate",
        "moderate",
        "elevated",
        "elevated",
        "high",
        "high",
    ]


def test_size_alone_never_exceeds_moderate() -> None:
    a = combine(
        "transaction",
        "big",
        [_c("anomaly", 1, 0.3), _c("graph", 0, 0.25, available=False), _c("velocity", 0, 0.1, available=False)],
        value_only_anomaly=True,
        coinjoin=False,
        model_disagreement=None,
        quality=DataQuality.valid,
        evidence={},
    )
    assert a.score <= 49 and any("value/size-only" in c for c in a.caps)


def test_coinjoin_capped_and_explained() -> None:
    a = combine(
        "transaction",
        "cj",
        [_c("anomaly", 1, 0.3), _c("graph", 1, 0.25)],
        value_only_anomaly=False,
        coinjoin=True,
        model_disagreement=None,
        quality=DataQuality.valid,
        evidence={},
    )
    assert a.score <= 49 and "privacy" in a.explanation


def test_unavailable_components_raise_uncertainty_not_score() -> None:
    full = combine(
        "transaction",
        "a",
        [_c("anomaly", 0.5, 0.3), _c("network", 0, 0.15)],
        value_only_anomaly=False,
        coinjoin=False,
        model_disagreement=None,
        quality=DataQuality.valid,
        evidence={},
    )
    missing = combine(
        "transaction",
        "b",
        [_c("anomaly", 0.5, 0.3), _c("network", 0, 0.15, available=False)],
        value_only_anomaly=False,
        coinjoin=False,
        model_disagreement=None,
        quality=DataQuality.valid,
        evidence={},
    )
    assert missing.uncertainty > full.uncertainty
    assert "investigative lead" in missing.explanation


async def _ingest(client: AsyncClient, h: dict[str, str], path: Path) -> None:
    with path.open("rb") as f:
        ds = (
            await client.post("/api/v1/ingestion/datasets", headers=h, data={"name": "syn"}, files={"files": (path.name, f)})
        ).json()
    r = await client.post(f"/api/v1/ingestion/datasets/{ds['id']}/process", headers=h)
    assert r.json()[0]["status"] == "completed_with_errors", r.text


async def test_end_to_end_ml_risk_alerts(
    client: AsyncClient, admin: dict[str, str], small_dataset: dict[str, Path], session
) -> None:  # type: ignore[no-untyped-def]
    await _ingest(client, admin, small_dataset["jsonl"])
    labels_path = small_dataset["jsonl"].with_name("synthetic_small.labels.json")
    labels = json.loads(labels_path.read_text())

    # models auto-trained and versioned
    models = (await client.get("/api/v1/ai/models", headers=admin)).json()
    assert {m["algorithm"] for m in models} == {"isolation_forest", "local_outlier_factor"}
    assert sum(m["is_active"] for m in models if m["entity_type"] == "transaction") == 1
    assert all(len(m["artifact_sha256"]) == 64 and m["training_snapshot"]["split"] == "time-ordered" for m in models)
    assert all(m["evaluation"]["label_source"] == "none" for m in models)  # no labels imported yet -> no accuracy claims

    # import synthetic labels and retrain -> labelled evaluation with explicit caveat
    with labels_path.open("rb") as f:
        r = await client.post("/api/v1/ai/labels/import", headers=admin, files={"file": ("labels.json", f)})
    assert r.status_code == 200 and r.json()["imported"] > 0
    assert (await session.scalar(select(func.count()).select_from(EvaluationLabel))) > 0
    r = await client.post("/api/v1/ai/models/train", headers=admin, json={"entity_type": "transaction", "seed": 42})
    assert r.status_code == 201
    evals = (await client.get("/api/v1/ai/models/evaluation", headers=admin)).json()
    labelled = [e for e in evals if e["label_source"] == "synthetic_injected"]
    assert labelled and "SYNTHETIC" in labelled[0]["caveats"] and "pr_auc" in labelled[0]["metrics"]

    # analysis is reproducible: on-demand rescoring equals the stored prediction
    fan = next(p for p in labels["patterns"] if p["pattern"] == "fan_out_split")["txids"][0]
    an = (await client.post("/api/v1/ai/analyze/transaction", headers=admin, json={"txid": fan})).json()
    stored = (await client.get("/api/v1/ai/predictions", headers=admin, params={"limit": 500})).json()["items"]
    match = next((p for p in stored if p["entity_key"] == fan), None)
    if match:
        assert abs(match["anomaly_score"] - an["prediction"]["anomaly_score"]) < 1e-6
    risk = (await client.get(f"/api/v1/transactions/{fan}/risk", headers=admin)).json()
    assert risk["available"] and 0 <= risk["score"] <= 100 and risk["components"] and "not evidence" in risk["limitations"]
    assert risk["band"] in ("elevated", "high")

    # benign controls are not prioritised
    for p in labels["patterns"]:
        if p["pattern"] in ("coinjoin_like", "large_normal"):
            rr = (await client.get(f"/api/v1/transactions/{p['txids'][0]}/risk", headers=admin)).json()
            assert rr["score"] < 50, (p["pattern"], rr["score"], rr["explanation"])

    # alerts generated from detections only; every alert explains itself
    alerts = (await client.get("/api/v1/alerts", headers=admin, params={"limit": 500})).json()
    assert alerts["total"] > 0
    for a in alerts["items"]:
        assert (
            a["explanation"] and a["triggered_rules"] and a["uncertainty_notes"] and a["confidence"] in ("low", "medium", "high")
        )
        assert a["evidence_refs"] or a["risk_assessment_id"]
    cats = {a["category"] for a in alerts["items"]}
    assert {"high_fan_out", "network_blockchain_correlation_anomaly"} <= cats

    # dedup: rerunning detection creates no new alerts
    before = alerts["total"]
    stats = await generate(get_sessionmaker())
    assert stats["created"] == 0 and stats["deduplicated"] == before


async def test_risk_recalculation_supersedes_with_reason(
    client: AsyncClient, admin: dict[str, str], small_dataset: dict[str, Path], session
) -> None:  # type: ignore[no-untyped-def]
    await _ingest(client, admin, small_dataset["jsonl"])
    # First recalculation absorbs alert history created after the pipeline's risk stage; the next must be a no-op.
    await assess_all(get_sessionmaker())
    n_current = await session.scalar(select(func.count()).select_from(RiskAssessment).where(RiskAssessment.is_current.is_(True)))
    again = await assess_all(get_sessionmaker())
    assert again["created"] == 0 and again["unchanged"] == n_current
    session.add(SystemConfig(key="risk_weights", value={"anomaly": 0.6}))
    await session.commit()
    changed = await assess_all(get_sessionmaker())
    assert changed["superseded"] > 0
    row = (await session.execute(select(RiskAssessment).where(RiskAssessment.supersedes_id.is_not(None)).limit(1))).scalar_one()
    assert row.change_reason and "score" in row.change_reason
    old = await session.get(RiskAssessment, row.supersedes_id)
    assert old is not None and old.is_current is False
    dup = await session.scalar(
        select(func.count()).select_from(
            select(RiskAssessment.entity_key)
            .where(RiskAssessment.is_current.is_(True))
            .group_by(RiskAssessment.entity_type, RiskAssessment.entity_key)
            .having(func.count() > 1)
            .subquery()
        )
    )
    assert dup == 0


async def test_alert_workflow_and_permissions(
    client: AsyncClient, admin: dict[str, str], small_dataset: dict[str, Path], session
) -> None:  # type: ignore[no-untyped-def]
    await _ingest(client, admin, small_dataset["jsonl"])
    a = (await client.get("/api/v1/alerts", headers=admin, params={"limit": 1, "category": "high_fan_out"})).json()["items"][0]
    aid = a["id"]
    viewer = await auth_headers(client, "viewer")
    analyst = await auth_headers(client, "analyst")
    senior = await auth_headers(client, "senior_analyst")
    assert (await client.post(f"/api/v1/alerts/{aid}/acknowledge", headers=viewer)).status_code == 403
    r = await client.post(f"/api/v1/alerts/{aid}/acknowledge", headers=analyst)
    assert r.status_code == 200 and r.json()["status"] == "acknowledged" and r.json()["assigned_to"]
    assert "resolved" in r.json()["allowed_transitions"]
    r = await client.patch(f"/api/v1/alerts/{aid}", headers=analyst, json={"status": "new"})
    assert r.status_code == 422 and "allowed" in r.json()
    r = await client.patch(
        f"/api/v1/alerts/{aid}", headers=analyst, json={"status": "under_investigation", "note": "checking outputs"}
    )
    assert r.status_code == 200 and r.json()["notes"]
    assert (
        await client.post(f"/api/v1/alerts/{aid}/resolve", headers=analyst, json={"note": "fp", "false_positive": True})
    ).status_code == 403
    r = await client.patch(f"/api/v1/alerts/{aid}", headers=senior, json={"status": "escalated", "note": "needs senior review"})
    assert r.status_code == 200 and r.json()["status"] == "escalated"
    r = await client.post(
        f"/api/v1/alerts/{aid}/resolve", headers=senior, json={"note": "exchange batch payout", "false_positive": True}
    )
    assert (
        r.status_code == 200 and r.json()["status"] == "false_positive" and r.json()["resolution_note"] == "exchange batch payout"
    )
    fb = (await session.execute(select(EvaluationLabel).where(EvaluationLabel.source == "analyst_feedback"))).scalars().all()
    assert len(fb) == 1 and fb[0].label == "benign"
    actions = set((await session.execute(select(AuditLog.action).where(AuditLog.entity_id == aid))).scalars())
    assert {"alert.status_changed", "alert.assigned"} <= actions
    # manual alert
    r = await client.post(
        "/api/v1/alerts",
        headers=senior,
        json={
            "category": "suspicious_graph_pattern",
            "severity": "moderate",
            "title": "Manual lead",
            "entity_type": "address",
            "entity_key": a["addresses"][0],
            "explanation": "Analyst observed repeated payments to this address.",
        },
    )
    assert r.status_code == 201 and r.json()["detection_method"] == "analyst_manual"
    assert (await client.post("/api/v1/alerts", headers=analyst, json={**r.json(), "explanation": "x" * 20})).status_code in (
        403,
        422,
    )
    assert await session.scalar(select(func.count()).select_from(Alert).where(Alert.detection_method == "analyst_manual")) == 1
