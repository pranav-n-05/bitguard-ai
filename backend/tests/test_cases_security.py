"""Investigations, evidence integrity, reports, administration and security controls (SYNTHETIC data)."""

import hashlib
import json
from pathlib import Path

import pyotp
import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.config import get_settings
from app.models import DatasetFile
from tests.conftest import PASSWORD, auth_headers


async def _ingest(client: AsyncClient, h: dict[str, str], path: Path) -> None:
    with path.open("rb") as f:
        ds = (
            await client.post("/api/v1/ingestion/datasets", headers=h, data={"name": "syn"}, files={"files": (path.name, f)})
        ).json()
    await client.post(f"/api/v1/ingestion/datasets/{ds['id']}/process", headers=h)


async def test_full_investigation_workflow(
    client: AsyncClient, admin: dict[str, str], small_dataset: dict[str, Path], session
) -> None:  # type: ignore[no-untyped-def]
    await _ingest(client, admin, small_dataset["jsonl"])
    analyst = await auth_headers(client, "analyst")
    viewer = await auth_headers(client, "viewer")
    alert = (await client.get("/api/v1/alerts", headers=analyst, params={"limit": 1, "category": "high_fan_out"})).json()[
        "items"
    ][0]

    r = await client.post(
        "/api/v1/investigations",
        headers=analyst,
        json={
            "title": "Fan-out splitting lead",
            "summary": "Opened from automated alert",
            "priority": "elevated",
            "alert_ids": [alert["id"]],
            "txids": [alert["txid"]],
        },
    )
    assert r.status_code == 201, r.text
    case = r.json()
    cid = case["id"]
    assert case["case_number"].startswith("BG-") and case["assigned_to"]
    assert (await client.post("/api/v1/investigations", headers=viewer, json={"title": "nope"})).status_code == 403

    # linking unknown entities is rejected
    assert (
        await client.post(f"/api/v1/investigations/{cid}/entities", headers=analyst, json={"txids": ["ab" * 32]})
    ).status_code == 404
    r = await client.post(f"/api/v1/investigations/{cid}/entities", headers=analyst, json={"addresses": alert["addresses"][:3]})
    assert r.json()["addresses"] == 3

    assert (
        await client.post(
            f"/api/v1/investigations/{cid}/notes", headers=analyst, json={"body": "Outputs look like a payout batch?"}
        )
    ).status_code == 201

    ev = await client.post(
        f"/api/v1/investigations/{cid}/evidence",
        headers=analyst,
        json={"evidence_type": "transaction", "reference": alert["txid"], "description": "Anchor transaction of the fan-out"},
    )
    assert ev.status_code == 201, ev.text
    e = ev.json()
    assert len(e["integrity_hash"]) == 64 and e["source_file_sha256"] and e["record_hash"] and e["snapshot"]["risk"]
    assert e["analysis_version"]["risk_rule_version"] and e["analysis_version"]["active_models"]
    ev2 = await client.post(
        f"/api/v1/investigations/{cid}/evidence",
        headers=analyst,
        json={"evidence_type": "alert", "reference": alert["id"], "description": "Automated alert"},
    )
    assert ev2.status_code == 201

    v = (await client.get(f"/api/v1/investigations/{cid}/evidence/{e['id']}/verify", headers=viewer)).json()
    assert v["verified"] is True and v["source_file_sha256_matches"] is True

    # evidence records are append-only at the database level
    with pytest.raises(DBAPIError, match="append-only"):
        await session.execute(text("UPDATE evidence_records SET description='x' WHERE id=:i").bindparams(i=e["id"]))
    await session.rollback()

    detail = (await client.get(f"/api/v1/investigations/{cid}", headers=viewer)).json()
    assert len(detail["evidence"]) == 2 and detail["notes"] and detail["transactions"] and detail["alerts"]
    actions = [t["action"] for t in detail["timeline"]]
    assert actions[0] == "case.created" and "case.evidence_attached" in actions

    # assignment requires case.assign
    senior_id = None
    users = (await client.get("/api/v1/admin/users/assignable", headers=analyst)).json()
    senior_id = next(u["id"] for u in users if u["email"].startswith("senior"))
    assert (
        await client.patch(f"/api/v1/investigations/{cid}", headers=analyst, json={"assigned_to": senior_id})
    ).status_code == 403
    senior = await auth_headers(client, "senior_analyst")
    assert (
        await client.patch(f"/api/v1/investigations/{cid}", headers=senior, json={"assigned_to": senior_id})
    ).status_code == 200

    # export reports in every format; downloads verify sha256
    for fmt in ("pdf", "json", "csv"):
        rep = await client.post(f"/api/v1/investigations/{cid}/export", headers=analyst, json={"format": fmt})
        assert rep.status_code == 201, rep.text
        meta = rep.json()
        dl = await client.get(f"/api/v1/reports/{meta['id']}/download", headers=analyst)
        assert (
            dl.status_code == 200 and hashlib.sha256(dl.content).hexdigest() == meta["sha256"] == dl.headers["X-Content-SHA256"]
        )
        if fmt == "pdf":
            assert dl.content.startswith(b"%PDF")
        if fmt == "json":
            body = json.loads(dl.content)
            assert body["case"]["case_number"] == case["case_number"] and "not legal conclusions" in body["disclaimer"]

    # closing requires an analyst decision; closed cases accept no evidence
    assert (await client.patch(f"/api/v1/investigations/{cid}", headers=analyst, json={"status": "closed"})).status_code == 422
    r = await client.patch(
        f"/api/v1/investigations/{cid}",
        headers=analyst,
        json={"status": "closed", "analyst_decision": "Consistent with exchange batch payout; no further action."},
    )
    assert r.status_code == 200 and r.json()["closed_at"]
    assert (
        await client.post(
            f"/api/v1/investigations/{cid}/evidence",
            headers=analyst,
            json={"evidence_type": "transaction", "reference": alert["txid"], "description": "late"},
        )
    ).status_code == 422

    # tampering with the source file is detected by evidence verification
    df = (await session.execute(select(DatasetFile))).scalars().first()
    Path(df.storage_path).write_bytes(Path(df.storage_path).read_bytes() + b"\n")
    v = (await client.get(f"/api/v1/investigations/{cid}/evidence/{e['id']}/verify", headers=viewer)).json()
    assert v["verified"] is False and v["source_file_sha256_matches"] is False and v["integrity_hash_matches"] is True

    # tampering with a stored report is detected on download
    reps = (await client.get("/api/v1/reports", headers=viewer, params={"investigation_id": cid})).json()["items"]
    from app.models import ReportRecord

    rec = await session.get(ReportRecord, __import__("uuid").UUID(reps[0]["id"]))
    Path(rec.storage_path).write_bytes(b"tampered")
    assert (await client.get(f"/api/v1/reports/{rec.id}/download", headers=analyst)).status_code == 409


async def test_alert_and_transaction_reports(client: AsyncClient, admin: dict[str, str], small_dataset: dict[str, Path]) -> None:
    await _ingest(client, admin, small_dataset["jsonl"])
    for rt, fmt in (("alerts", "csv"), ("alerts", "pdf"), ("transactions", "json"), ("transactions", "csv")):
        r = await client.post(
            "/api/v1/reports/generate", headers=admin, json={"report_type": rt, "format": fmt, "parameters": {}}
        )
        assert r.status_code == 201, r.text
    assert (
        await client.post("/api/v1/reports/generate", headers=admin, json={"report_type": "transactions", "format": "pdf"})
    ).status_code == 400


RBAC = [  # (method, path, body, {role: expected_status})
    ("get", "/api/v1/transactions", None, {"viewer": 200, "analyst": 200}),
    ("get", "/api/v1/admin/users", None, {"viewer": 403, "analyst": 403, "senior_analyst": 403, "administrator": 200}),
    ("get", "/api/v1/admin/audit-logs", None, {"viewer": 403, "analyst": 403, "senior_analyst": 200}),
    ("get", "/api/v1/admin/configuration", None, {"senior_analyst": 403, "administrator": 200}),
    ("post", "/api/v1/ai/models/train", {"entity_type": "transaction"}, {"viewer": 403, "analyst": 403}),
    ("post", "/api/v1/reports/generate", {"report_type": "alerts", "format": "json"}, {"viewer": 403, "analyst": 201}),
    (
        "post",
        "/api/v1/alerts",
        {
            "category": "high_fan_out",
            "severity": "low",
            "title": "x" * 5,
            "entity_type": "address",
            "entity_key": "abc",
            "explanation": "x" * 20,
        },
        {"analyst": 403, "senior_analyst": 201},
    ),
    ("post", "/api/v1/admin/pipeline/rerun", None, {"analyst": 403, "senior_analyst": 403}),
]


@pytest.mark.parametrize(("method", "path", "body", "expect"), RBAC)
async def test_rbac_matrix(client: AsyncClient, method: str, path: str, body: dict | None, expect: dict[str, int]) -> None:  # type: ignore[type-arg]
    for role, code in expect.items():
        h = await auth_headers(client, role)
        r = await getattr(client, method)(path, headers=h, **({"json": body} if body is not None else {}))
        assert r.status_code == code, (role, path, r.status_code, r.text[:200])


async def test_mfa_flow(client: AsyncClient) -> None:
    h = await auth_headers(client, "analyst")
    setup = (await client.post("/api/v1/auth/mfa/setup", headers=h)).json()
    assert setup["otpauth_uri"].startswith("otpauth://totp/")
    totp = pyotp.TOTP(setup["secret"])
    assert (
        await client.post("/api/v1/auth/mfa/enable", headers=h, json={"otp": "000000" if totp.now() != "000000" else "111111"})
    ).status_code == 401
    assert (await client.post("/api/v1/auth/mfa/enable", headers=h, json={"otp": totp.now()})).status_code == 200
    assert (
        await client.post("/api/v1/auth/login", json={"email": "analyst@test.local", "password": PASSWORD})
    ).status_code == 401
    r = await client.post("/api/v1/auth/login", json={"email": "analyst@test.local", "password": PASSWORD, "otp": totp.now()})
    assert r.status_code == 200


async def test_rate_limit_on_login(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "login_rate_limit", "3/minute")
    from app.core.ratelimit import limiter

    limiter.reset()
    codes = [
        (await client.post("/api/v1/auth/login", json={"email": "viewer@test.local", "password": "bad"})).status_code
        for _ in range(5)
    ]
    assert codes[:3] == [401, 401, 401] and codes[3] == 429
    limiter.reset()


async def test_security_headers_and_body_limit(client: AsyncClient, admin: dict[str, str]) -> None:
    r = await client.get("/api/v1/health")
    for h in ("X-Content-Type-Options", "X-Frame-Options", "Content-Security-Policy", "Referrer-Policy"):
        assert h in r.headers
    assert r.headers["Cache-Control"] == "no-store"
    big = "x" * (get_settings().max_json_body_kb * 1024 + 10)
    r = await client.post("/api/v1/alerts", headers={**admin, "Content-Type": "application/json"}, content=big)
    assert r.status_code == 413


async def test_error_responses_do_not_leak_internals(client: AsyncClient, admin: dict[str, str]) -> None:
    r = await client.get("/api/v1/transactions", headers=admin, params={"sort": "-password_hash"})
    assert r.status_code in (400, 422) and "Traceback" not in r.text
    r = await client.get("/api/v1/transactions", headers=admin, params={"q": "'; DROP TABLE transactions; --"})
    assert r.status_code == 200 and r.json()["total"] == 0


async def test_admin_user_management_and_audit_chain(client: AsyncClient, admin: dict[str, str]) -> None:
    weak = await client.post(
        "/api/v1/admin/users",
        headers=admin,
        json={"email": "new@test.local", "full_name": "N", "password": "short", "roles": ["analyst"]},
    )
    assert weak.status_code == 400 and "policy" in weak.json()["detail"]
    r = await client.post(
        "/api/v1/admin/users",
        headers=admin,
        json={"email": "new@test.local", "full_name": "New Analyst", "password": "Very-Strong-Pass-42", "roles": ["analyst"]},
    )
    assert r.status_code == 201
    uid = r.json()["id"]
    assert (
        await client.post("/api/v1/auth/login", json={"email": "new@test.local", "password": "Very-Strong-Pass-42"})
    ).status_code == 200
    r = await client.patch(f"/api/v1/admin/users/{uid}", headers=admin, json={"is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert (
        await client.post("/api/v1/auth/login", json={"email": "new@test.local", "password": "Very-Strong-Pass-42"})
    ).status_code == 401
    me = (await client.get("/api/v1/auth/me", headers=admin)).json()
    assert (await client.patch(f"/api/v1/admin/users/{me['id']}", headers=admin, json={"roles": ["viewer"]})).status_code == 400
    v = (await client.get("/api/v1/admin/audit-logs/verify", headers=admin)).json()
    assert v["valid"] is True and v["entries_checked"] > 0


async def test_configuration_change_is_versioned_and_validated(
    client: AsyncClient, admin: dict[str, str], small_dataset: dict[str, Path]
) -> None:
    await _ingest(client, admin, small_dataset["jsonl"])
    assert (
        await client.patch("/api/v1/admin/configuration", headers=admin, json={"risk_weights": {"bogus": 0.5}})
    ).status_code == 400
    r = await client.patch(
        "/api/v1/admin/configuration",
        headers=admin,
        json={
            "risk_weights": {"network": 0.3},
            "alert_rules": [{"code": "NET_IP_BURST", "thresholds": {"min_confidence": 0.99}}],
        },
    )
    assert r.status_code == 200 and r.json()["risk_weights"]["network"] == 0.3
    rule = next(x for x in r.json()["alert_rules"] if x["code"] == "NET_IP_BURST")
    assert rule["thresholds"]["min_confidence"] == 0.99 and rule["version"] == 2
    out = (await client.post("/api/v1/admin/pipeline/rerun", headers=admin, params={"stages": ["risk", "alerts"]})).json()
    assert out["risk"]["superseded"] > 0
