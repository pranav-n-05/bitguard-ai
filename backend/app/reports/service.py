"""Report generation (PDF / CSV / JSON). Every report is stored with a SHA-256 and recorded in report_records."""

import csv
import io
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError, IntegrityError, NotFoundError
from app.core.hashing import sha256_hex
from app.models import (
    Alert,
    AuditLog,
    EvidenceRecord,
    Investigation,
    InvestigationAddress,
    InvestigationAlert,
    InvestigationNote,
    InvestigationObservation,
    InvestigationTransaction,
    ReportRecord,
    RiskAssessment,
    Transaction,
    User,
)
from app.services import audit

DISCLAIMER = (
    "BITGUARD AI output. All findings are investigative leads derived from bulk transaction and network metadata, "
    "heuristics and unsupervised models. They are not legal conclusions, do not establish identity or ownership, and "
    "must be independently verified. Data provenance labels (synthetic/historical) apply to every figure."
)
FORMATS = {"investigation_summary": {"pdf", "json", "csv"}, "alerts": {"pdf", "json", "csv"}, "transactions": {"json", "csv"}}


def _json_default(o: Any) -> Any:
    if isinstance(o, datetime):
        return o.isoformat()
    if isinstance(o, uuid.UUID):
        return str(o)
    if hasattr(o, "value"):
        return o.value
    return str(o)


async def case_bundle(s: AsyncSession, case_id: uuid.UUID) -> dict[str, Any]:
    c = await s.get(Investigation, case_id)
    if c is None:
        raise NotFoundError("Investigation not found")
    users = {u.id: u.email for u in (await s.execute(select(User))).scalars()}
    txids = list(
        (
            await s.execute(select(InvestigationTransaction.txid).where(InvestigationTransaction.investigation_id == case_id))
        ).scalars()
    )
    addrs = list(
        (await s.execute(select(InvestigationAddress.address).where(InvestigationAddress.investigation_id == case_id))).scalars()
    )
    alert_ids = list(
        (await s.execute(select(InvestigationAlert.alert_id).where(InvestigationAlert.investigation_id == case_id))).scalars()
    )
    obs = list(
        (
            await s.execute(
                select(InvestigationObservation.observation_id).where(InvestigationObservation.investigation_id == case_id)
            )
        ).scalars()
    )
    risk = {
        (r.entity_type, r.entity_key): r
        for r in (
            await s.execute(
                select(RiskAssessment).where(RiskAssessment.is_current.is_(True), RiskAssessment.entity_key.in_(txids + addrs))
            )
        ).scalars()
    }
    txs = (await s.execute(select(Transaction).where(Transaction.txid.in_(txids)))).scalars().all()
    alerts = (await s.execute(select(Alert).where(Alert.id.in_(alert_ids)))).scalars().all()
    notes = (
        (
            await s.execute(
                select(InvestigationNote)
                .where(InvestigationNote.investigation_id == case_id)
                .order_by(InvestigationNote.created_at)
            )
        )
        .scalars()
        .all()
    )
    ev = (
        (
            await s.execute(
                select(EvidenceRecord).where(EvidenceRecord.investigation_id == case_id).order_by(EvidenceRecord.retrieved_at)
            )
        )
        .scalars()
        .all()
    )
    timeline = (
        (
            await s.execute(
                select(AuditLog)
                .where(AuditLog.entity_type == "investigation", AuditLog.entity_id == str(case_id))
                .order_by(AuditLog.seq)
            )
        )
        .scalars()
        .all()
    )
    return {
        "case": {
            "id": c.id,
            "case_number": c.case_number,
            "title": c.title,
            "summary": c.summary,
            "status": c.status,
            "priority": c.priority,
            "created_by": users.get(c.created_by),
            "assigned_to": users.get(c.assigned_to) if c.assigned_to else None,
            "analyst_decision": c.analyst_decision,
            "created_at": c.created_at,
            "closed_at": c.closed_at,
        },
        "transactions": [
            {
                "txid": t.txid,
                "first_seen_at": t.first_seen_at,
                "total_output_sat": t.total_output_sat,
                "fee_sat": t.fee_sat,
                "inputs": t.input_count,
                "outputs": t.output_count,
                "risk_score": risk[("transaction", t.txid)].score if ("transaction", t.txid) in risk else None,
                "risk_band": risk[("transaction", t.txid)].band if ("transaction", t.txid) in risk else None,
            }
            for t in txs
        ],
        "addresses": [
            {"address": a, "risk_score": risk[("address", a)].score if ("address", a) in risk else None} for a in addrs
        ],
        "alerts": [
            {
                "id": a.id,
                "category": a.category,
                "severity": a.severity,
                "status": a.status,
                "risk_score": a.risk_score,
                "explanation": a.explanation,
            }
            for a in alerts
        ],
        "network_observation_ids": obs,
        "notes": [{"author": users.get(n.author_id), "at": n.created_at, "body": n.body} for n in notes],
        "evidence": [
            {
                "id": e.id,
                "type": e.evidence_type,
                "reference": e.reference,
                "description": e.description,
                "integrity_hash": e.integrity_hash,
                "record_hash": e.record_hash,
                "source_file_sha256": e.source_file_sha256,
                "analysis_version": e.analysis_version,
                "retrieved_at": e.retrieved_at,
                "added_by": users.get(e.added_by),
            }
            for e in ev
        ],
        "timeline": [
            {
                "seq": a.seq,
                "at": a.occurred_at,
                "action": a.action,
                "actor": a.actor_email,
                "details": a.details,
                "entry_hash": a.entry_hash,
            }
            for a in timeline
        ],
        "disclaimer": DISCLAIMER,
    }


def _pdf(title: str, sections: list[tuple[str, Any]]) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=title,
        author="BITGUARD AI",
    )
    st = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=st["BodyText"], fontSize=8, leading=10)
    story: list[Any] = [
        Paragraph(title, st["Title"]),
        Paragraph(f"Generated {datetime.now(UTC).isoformat()} UTC", small),
        Spacer(1, 4 * mm),
        Paragraph(f"<b>Notice:</b> {DISCLAIMER}", small),
        Spacer(1, 4 * mm),
    ]
    for heading, body in sections:
        story.append(Paragraph(heading, st["Heading2"]))
        if isinstance(body, str):
            story.append(Paragraph(body.replace("\n", "<br/>") or "—", st["BodyText"]))
        elif isinstance(body, list) and body and isinstance(body[0], list):
            data = [[Paragraph(str(c) if c is not None else "unavailable", small) for c in row] for row in body]
            width = A4[0] - 30 * mm
            t = LongTable(data, repeatRows=1, colWidths=[width / len(data[0])] * len(data[0]))
            t.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#172033")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ]
                )
            )
            story.append(t)
        else:
            story.append(Paragraph("None recorded.", small))
        story.append(Spacer(1, 3 * mm))
    doc.build(story)
    return buf.getvalue()


def _short(v: Any, n: int = 18) -> str:
    s = str(v) if v is not None else "unavailable"
    return s if len(s) <= n else f"{s[: n // 2]}…{s[-n // 2 :]}"


def render_case(bundle: dict[str, Any], fmt: str) -> bytes:
    if fmt == "json":
        return json.dumps(bundle, default=_json_default, indent=1).encode()
    if fmt == "csv":
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["section", "key", "detail_1", "detail_2", "detail_3"])
        c = bundle["case"]
        w.writerow(["case", c["case_number"], c["title"], _json_default(c["status"]), _json_default(c["priority"])])
        for t in bundle["transactions"]:
            w.writerow(["transaction", t["txid"], t["total_output_sat"], t["risk_score"], _json_default(t["risk_band"])])
        for a in bundle["addresses"]:
            w.writerow(["address", a["address"], a["risk_score"], "", ""])
        for a in bundle["alerts"]:
            w.writerow(["alert", a["id"], a["category"], _json_default(a["severity"]), _json_default(a["status"])])
        for e in bundle["evidence"]:
            w.writerow(["evidence", e["id"], e["type"], e["reference"], e["integrity_hash"]])
        for n in bundle["notes"]:
            w.writerow(["note", _json_default(n["at"]), n["author"], n["body"], ""])
        w.writerow(["disclaimer", DISCLAIMER, "", "", ""])
        return out.getvalue().encode()
    c = bundle["case"]
    return _pdf(
        f"Investigation {c['case_number']}: {c['title']}",
        [
            (
                "Case",
                f"Status: {_json_default(c['status'])} · Priority: {_json_default(c['priority'])} · Assigned: {c['assigned_to'] or 'unassigned'}"
                f"<br/>Created by {c['created_by']} at {_json_default(c['created_at'])}<br/><br/>{c['summary'] or ''}",
            ),
            ("Analyst decision", c["analyst_decision"] or "No decision recorded."),
            (
                "Linked transactions",
                [["txid", "first seen", "value (sat)", "risk"]]
                + [
                    [
                        t["txid"],
                        _json_default(t["first_seen_at"]),
                        t["total_output_sat"],
                        f"{t['risk_score']} ({_json_default(t['risk_band'])})" if t["risk_score"] is not None else None,
                    ]
                    for t in bundle["transactions"]
                ]
                if bundle["transactions"]
                else [],
            ),
            (
                "Linked addresses",
                [["address", "risk"]] + [[a["address"], a["risk_score"]] for a in bundle["addresses"]]
                if bundle["addresses"]
                else [],
            ),
            (
                "Linked alerts",
                [["category", "severity", "status", "explanation"]]
                + [
                    [a["category"], _json_default(a["severity"]), _json_default(a["status"]), a["explanation"][:400]]
                    for a in bundle["alerts"]
                ]
                if bundle["alerts"]
                else [],
            ),
            (
                "Evidence (provenance & integrity)",
                [["#", "type", "reference", "integrity sha256", "source file sha256"]]
                + [
                    [e["id"], e["type"], _short(e["reference"], 24), e["integrity_hash"], e["source_file_sha256"]]
                    for e in bundle["evidence"]
                ]
                if bundle["evidence"]
                else [],
            ),
            (
                "Notes",
                [["when", "author", "note"]] + [[_json_default(n["at"]), n["author"], n["body"]] for n in bundle["notes"]]
                if bundle["notes"]
                else [],
            ),
            (
                "Audit timeline",
                [["seq", "when", "action", "actor", "entry hash"]]
                + [
                    [t["seq"], _json_default(t["at"]), t["action"], t["actor"], _short(t["entry_hash"], 20)]
                    for t in bundle["timeline"]
                ],
            ),
            (
                "Limitations",
                "Address-level linkage (no outpoints), heuristic clustering and network co-occurrence cannot establish "
                "ownership or identity. Model scores are outlier ranks, not probabilities. See Known Limitations document.",
            ),
        ],
    )


async def _alerts_rows(s: AsyncSession, params: dict[str, Any]) -> list[dict[str, Any]]:
    q = select(Alert).order_by(Alert.created_at.desc()).limit(min(int(params.get("limit", 5000)), 20000))
    if params.get("status"):
        q = q.where(Alert.status.in_(params["status"]))
    if params.get("severity"):
        q = q.where(Alert.severity.in_(params["severity"]))
    return [
        {
            "id": a.id,
            "created_at": a.created_at,
            "category": a.category,
            "severity": a.severity,
            "status": a.status,
            "entity_type": a.entity_type,
            "entity_key": a.entity_key,
            "txid": a.txid,
            "risk_score": a.risk_score,
            "confidence": a.confidence,
            "detection_method": a.detection_method,
            "explanation": a.explanation,
        }
        for a in (await s.execute(q)).scalars()
    ]


async def _tx_rows(s: AsyncSession, params: dict[str, Any]) -> list[dict[str, Any]]:
    q = select(Transaction).order_by(Transaction.first_seen_at).limit(min(int(params.get("limit", 10000)), 100000))
    if params.get("start"):
        q = q.where(Transaction.first_seen_at >= datetime.fromisoformat(params["start"]))
    if params.get("end"):
        q = q.where(Transaction.first_seen_at <= datetime.fromisoformat(params["end"]))
    rows = (await s.execute(q)).scalars().all()
    risk = {
        r.entity_key: r
        for r in (
            await s.execute(
                select(RiskAssessment).where(
                    RiskAssessment.is_current.is_(True),
                    RiskAssessment.entity_type == "transaction",
                    RiskAssessment.entity_key.in_([t.txid for t in rows]),
                )
            )
        ).scalars()
    }
    return [
        {
            "txid": t.txid,
            "first_seen_at": t.first_seen_at,
            "total_input_sat": t.total_input_sat,
            "total_output_sat": t.total_output_sat,
            "fee_sat": t.fee_sat,
            "inputs": t.input_count,
            "outputs": t.output_count,
            "data_quality": t.data_quality,
            "risk_score": risk[t.txid].score if t.txid in risk else None,
            "risk_band": risk[t.txid].band if t.txid in risk else None,
        }
        for t in rows
    ]


def _table(rows: list[dict[str, Any]], fmt: str, title: str) -> bytes:
    if fmt == "json":
        return json.dumps(
            {"title": title, "generated_at": datetime.now(UTC), "disclaimer": DISCLAIMER, "rows": rows},
            default=_json_default,
            indent=1,
        ).encode()
    if fmt == "csv":
        out = io.StringIO()
        if rows:
            w = csv.DictWriter(out, fieldnames=list(rows[0]))
            w.writeheader()
            for r in rows:
                w.writerow(
                    {k: _json_default(v) if v is not None and not isinstance(v, str | int | float) else v for k, v in r.items()}
                )
        return out.getvalue().encode()
    cols = ["created_at", "category", "severity", "status", "entity_key", "risk_score"]
    return _pdf(
        title,
        [("Alerts", [cols] + [[_json_default(r[c]) if r[c] is not None else None for c in cols] for r in rows] if rows else [])],
    )


async def generate(s: AsyncSession, user: User, report_type: str, fmt: str, params: dict[str, Any]) -> ReportRecord:
    if fmt not in FORMATS.get(report_type, set()):
        raise AppError(f"Unsupported report_type/format; allowed: { {k: sorted(v) for k, v in FORMATS.items()} }")
    case_id = None
    if report_type == "investigation_summary":
        if not params.get("investigation_id"):
            raise AppError("investigation_id is required")
        case_id = uuid.UUID(str(params["investigation_id"]))
        data = render_case(await case_bundle(s, case_id), fmt)
    elif report_type == "alerts":
        data = _table(await _alerts_rows(s, params), fmt, "BITGUARD AI — Alert register")
    else:
        data = _table(await _tx_rows(s, params), fmt, "BITGUARD AI — Transactions")
    rid = uuid.uuid4()
    d = get_settings().storage_dir / "reports"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{rid}.{fmt}"
    path.write_bytes(data)
    rec = ReportRecord(
        id=rid,
        report_type=report_type,
        format=fmt,
        investigation_id=case_id,
        parameters=json.loads(json.dumps(params, default=str)),
        storage_path=str(path.resolve()),
        sha256=sha256_hex(data),
        size_bytes=len(data),
        generated_by=user.id,
    )
    s.add(rec)
    await s.flush()
    await audit.record(
        s,
        "report.generated",
        "report",
        str(rid),
        actor_id=user.id,
        actor_email=user.email,
        details={"type": report_type, "format": fmt, "sha256": rec.sha256, "investigation_id": str(case_id) if case_id else None},
    )
    if case_id:
        await audit.record(
            s,
            "case.report_exported",
            "investigation",
            str(case_id),
            actor_id=user.id,
            actor_email=user.email,
            details={"report_id": str(rid), "format": fmt, "sha256": rec.sha256},
        )
    return rec


def read_verified(rec: ReportRecord) -> bytes:
    p = Path(rec.storage_path)
    if not p.exists():
        raise NotFoundError("Report file missing from storage")
    data = p.read_bytes()
    if sha256_hex(data) != rec.sha256:
        raise IntegrityError("Report file failed integrity verification")
    return data
