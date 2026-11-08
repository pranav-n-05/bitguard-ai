"""Investigation cases, linked entities, notes and append-only evidence with provenance + integrity hashes."""

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.features import SCHEMA_VERSION
from app.core.errors import AppError, InvalidStateError, NotFoundError, PermissionDeniedError
from app.core.hashing import content_hash, file_sha256
from app.models import (
    Address,
    Alert,
    AnalysisRun,
    Dataset,
    DatasetFile,
    EvidenceRecord,
    Investigation,
    InvestigationAddress,
    InvestigationAlert,
    InvestigationNote,
    InvestigationObservation,
    InvestigationTransaction,
    ModelVersion,
    NetworkObservation,
    RawRecord,
    RiskAssessment,
    Transaction,
    User,
)
from app.models.base import CaseStatus
from app.services import audit
from app.services.risk import RULE_VERSION

CASE_TRANSITIONS = {
    CaseStatus.open: {CaseStatus.in_progress, CaseStatus.on_hold, CaseStatus.closed},
    CaseStatus.in_progress: {CaseStatus.on_hold, CaseStatus.closed},
    CaseStatus.on_hold: {CaseStatus.in_progress, CaseStatus.closed},
    CaseStatus.closed: {CaseStatus.in_progress},
}


async def get_case(s: AsyncSession, case_id: uuid.UUID, lock: bool = False) -> Investigation:
    c = await s.get(Investigation, case_id, with_for_update=lock)
    if c is None:
        raise NotFoundError("Investigation not found")
    return c


async def _next_case_number(s: AsyncSession) -> str:
    year = datetime.now(UTC).year
    n = await s.scalar(select(func.count()).select_from(Investigation).where(Investigation.case_number.like(f"BG-{year}-%"))) or 0
    return f"BG-{year}-{n + 1:05d}"


async def _assert_assignable(s: AsyncSession, user_id: uuid.UUID) -> None:
    u = await s.get(User, user_id)
    if u is None or not u.is_active or "case.create" not in u.permission_codes:
        raise InvalidStateError("Assignee must be an active user permitted to work cases")


async def create(
    s: AsyncSession,
    user: User,
    title: str,
    summary: str | None,
    priority: Any,
    assigned_to: uuid.UUID | None,
    links: dict[str, list[Any]],
) -> Investigation:
    if assigned_to and assigned_to != user.id:
        if "case.assign" not in user.permission_codes:
            raise PermissionDeniedError("Missing permission: case.assign")
        await _assert_assignable(s, assigned_to)
    await s.execute(select(func.pg_advisory_xact_lock(0x63617365)))  # serialise case numbering
    c = Investigation(
        case_number=await _next_case_number(s),
        title=title,
        summary=summary,
        priority=priority,
        created_by=user.id,
        assigned_to=assigned_to or user.id,
    )
    s.add(c)
    await s.flush()
    await audit.record(
        s,
        "case.created",
        "investigation",
        str(c.id),
        actor_id=user.id,
        actor_email=user.email,
        details={"case_number": c.case_number, "title": title},
    )
    await link(s, c, user, links)
    return c


async def link(s: AsyncSession, c: Investigation, user: User, links: dict[str, list[Any]]) -> dict[str, int]:
    added = {"transactions": 0, "addresses": 0, "alerts": 0, "observations": 0}
    txids = [t.lower() for t in links.get("txids", [])]
    if txids:
        found = set((await s.execute(select(Transaction.txid).where(Transaction.txid.in_(txids)))).scalars())
        if missing := set(txids) - found:
            raise NotFoundError(f"Unknown txid(s): {sorted(missing)[:5]}")
        r = await s.execute(
            pg_insert(InvestigationTransaction)
            .values([{"investigation_id": c.id, "txid": t, "added_by": user.id} for t in found])
            .on_conflict_do_nothing()
            .returning(InvestigationTransaction.txid)
        )
        added["transactions"] = len(r.all())
    addrs = links.get("addresses", [])
    if addrs:
        found = set((await s.execute(select(Address.address).where(Address.address.in_(addrs)))).scalars())
        if missing := set(addrs) - found:
            raise NotFoundError(f"Unknown address(es): {sorted(missing)[:5]}")
        r = await s.execute(
            pg_insert(InvestigationAddress)
            .values([{"investigation_id": c.id, "address": a, "added_by": user.id} for a in found])
            .on_conflict_do_nothing()
            .returning(InvestigationAddress.address)
        )
        added["addresses"] = len(r.all())
    alert_ids = [uuid.UUID(str(a)) for a in links.get("alert_ids", [])]
    if alert_ids:
        found_a = set((await s.execute(select(Alert.id).where(Alert.id.in_(alert_ids)))).scalars())
        if missing_a := set(alert_ids) - found_a:
            raise NotFoundError(f"Unknown alert(s): {[str(m) for m in list(missing_a)[:5]]}")
        r = await s.execute(
            pg_insert(InvestigationAlert)
            .values([{"investigation_id": c.id, "alert_id": a, "added_by": user.id} for a in found_a])
            .on_conflict_do_nothing()
            .returning(InvestigationAlert.alert_id)
        )
        added["alerts"] = len(r.all())
    obs = [int(o) for o in links.get("observation_ids", [])]
    if obs:
        found_o = set((await s.execute(select(NetworkObservation.id).where(NetworkObservation.id.in_(obs)))).scalars())
        if missing_o := set(obs) - found_o:
            raise NotFoundError(f"Unknown observation(s): {sorted(missing_o)[:5]}")
        r = await s.execute(
            pg_insert(InvestigationObservation)
            .values([{"investigation_id": c.id, "observation_id": o, "added_by": user.id} for o in found_o])
            .on_conflict_do_nothing()
            .returning(InvestigationObservation.observation_id)
        )
        added["observations"] = len(r.all())
    if any(added.values()):
        await audit.record(
            s,
            "case.entities_linked",
            "investigation",
            str(c.id),
            actor_id=user.id,
            actor_email=user.email,
            details={
                "added": added,
                "txids": txids[:50],
                "addresses": addrs[:50],
                "alert_ids": [str(a) for a in alert_ids][:50],
                "observation_ids": obs[:50],
            },
        )
    return added


async def update(s: AsyncSession, c: Investigation, user: User, changes: dict[str, Any]) -> Investigation:
    diff: dict[str, Any] = {}
    if "assigned_to" in changes and changes["assigned_to"] != c.assigned_to:
        if "case.assign" not in user.permission_codes:
            raise PermissionDeniedError("Missing permission: case.assign")
        if changes["assigned_to"] is not None:
            await _assert_assignable(s, changes["assigned_to"])
        diff["assigned_to"] = [
            str(c.assigned_to) if c.assigned_to else None,
            str(changes["assigned_to"]) if changes["assigned_to"] else None,
        ]
        c.assigned_to = changes["assigned_to"]
    if (st := changes.get("status")) and st != c.status:
        if st not in CASE_TRANSITIONS[c.status]:
            raise InvalidStateError(f"Cannot move case from {c.status.value} to {st.value}")
        if st == CaseStatus.closed and not (changes.get("analyst_decision") or c.analyst_decision):
            raise InvalidStateError("An analyst decision is required to close a case")
        diff["status"] = [c.status.value, st.value]
        c.status = st
        c.closed_at = datetime.now(UTC) if st == CaseStatus.closed else None
    for f in ("title", "summary", "priority", "analyst_decision"):
        if f in changes and changes[f] is not None and changes[f] != getattr(c, f):
            old = getattr(c, f)
            diff[f] = [getattr(old, "value", old), getattr(changes[f], "value", changes[f])]
            setattr(c, f, changes[f])
    if diff:
        await audit.record(s, "case.updated", "investigation", str(c.id), actor_id=user.id, actor_email=user.email, details=diff)
    return c


async def add_note(s: AsyncSession, c: Investigation, user: User, body: str) -> InvestigationNote:
    n = InvestigationNote(investigation_id=c.id, author_id=user.id, body=body)
    s.add(n)
    await s.flush()
    await audit.record(
        s, "case.note_added", "investigation", str(c.id), actor_id=user.id, actor_email=user.email, details={"note_id": n.id}
    )
    return n


async def _analysis_versions(s: AsyncSession) -> dict[str, Any]:
    run = (
        (await s.execute(select(AnalysisRun).where(AnalysisRun.status == "completed").order_by(AnalysisRun.finished_at.desc())))
        .scalars()
        .first()
    )
    models = {
        m.entity_type: f"{m.name}@{m.version}#{m.artifact_sha256[:12]}"
        for m in (await s.execute(select(ModelVersion).where(ModelVersion.is_active.is_(True)))).scalars()
    }
    return {
        "analysis_run_id": run.id if run else None,
        "feature_schema": SCHEMA_VERSION,
        "risk_rule_version": RULE_VERSION,
        "active_models": models,
    }


async def _risk_snapshot(s: AsyncSession, et: str, key: str) -> dict[str, Any] | None:
    r = (
        (
            await s.execute(
                select(RiskAssessment).where(
                    RiskAssessment.entity_type == et, RiskAssessment.entity_key == key, RiskAssessment.is_current.is_(True)
                )
            )
        )
        .scalars()
        .first()
    )
    return {"assessment_id": r.id, "score": r.score, "band": r.band.value, "rule_version": r.rule_version} if r else None


async def attach_evidence(
    s: AsyncSession, c: Investigation, user: User, evidence_type: str, reference: str, description: str
) -> EvidenceRecord:
    if c.status == CaseStatus.closed:
        raise InvalidStateError("Cannot attach evidence to a closed case")
    prov: dict[str, Any] = {}
    snap: dict[str, Any] = {"evidence_type": evidence_type, "reference": reference}
    raw: RawRecord | None = None
    if evidence_type == "transaction":
        t = (await s.execute(select(Transaction).where(Transaction.txid == reference.lower()))).scalar_one_or_none()
        if t is None:
            raise NotFoundError("Transaction not found")
        raw = await s.get(RawRecord, t.source_raw_record_id)
        snap.update(
            txid=t.txid,
            first_seen_at=t.first_seen_at.isoformat(),
            total_input_sat=t.total_input_sat,
            total_output_sat=t.total_output_sat,
            fee_sat=t.fee_sat,
            input_count=t.input_count,
            output_count=t.output_count,
            content_hash=t.content_hash,
            block_height=t.block_height,
            risk=await _risk_snapshot(s, "transaction", t.txid),
        )
        prov.update(txid=t.txid, block_hash=t.block_hash)
        await link(s, c, user, {"txids": [t.txid]})
    elif evidence_type == "address":
        a = await s.get(Address, reference)
        if a is None:
            raise NotFoundError("Address not found")
        snap.update(
            address=a.address,
            address_type=a.address_type,
            first_seen_at=a.first_seen_at.isoformat(),
            last_seen_at=a.last_seen_at.isoformat(),
            risk=await _risk_snapshot(s, "address", a.address),
        )
        await link(s, c, user, {"addresses": [a.address]})
    elif evidence_type == "observation":
        o = await s.get(NetworkObservation, int(reference)) if reference.isdigit() else None
        if o is None:
            raise NotFoundError("Network observation not found")
        raw = await s.get(RawRecord, o.source_raw_record_id)
        snap.update(
            observation_id=o.id,
            txid=o.txid,
            observed_at=o.observed_at.isoformat(),
            src_ip=str(o.src_ip),
            dst_ip=str(o.dst_ip),
            src_port=o.src_port,
            dst_port=o.dst_port,
            asn=o.asn,
            country=o.geo_country,
            notice="Co-occurrence only; does not identify who controls any address.",
        )
        prov.update(txid=o.txid)
        await link(s, c, user, {"observation_ids": [o.id]})
    elif evidence_type == "alert":
        al = await s.get(Alert, uuid.UUID(reference)) if _is_uuid(reference) else None
        if al is None:
            raise NotFoundError("Alert not found")
        snap.update(
            alert_id=str(al.id),
            category=al.category,
            severity=al.severity.value,
            status=al.status.value,
            risk_score=al.risk_score,
            explanation=al.explanation,
            triggered_rules=al.triggered_rules,
        )
        prov.update(txid=al.txid)
        await link(s, c, user, {"alert_ids": [al.id]})
    elif evidence_type == "raw_record":
        raw = await s.get(RawRecord, int(reference)) if reference.isdigit() else None
        if raw is None:
            raise NotFoundError("Raw record not found")
        snap.update(raw_record_id=raw.id, payload=raw.payload, data_quality=raw.data_quality.value)
    else:
        raise AppError("evidence_type must be transaction|address|observation|alert|raw_record")
    if raw is not None:
        df = await s.get(DatasetFile, raw.dataset_file_id)
        ds = await s.get(Dataset, raw.dataset_id)
        assert df is not None and ds is not None
        prov.update(
            source_dataset_id=raw.dataset_id,
            source_file_id=df.id,
            source_file_sha256=df.sha256,
            raw_record_id=raw.id,
            record_hash=raw.content_hash,
        )
        snap["source"] = {
            "dataset": ds.name,
            "provenance": ds.provenance,
            "file": df.original_name,
            "file_sha256": df.sha256,
            "record_index": raw.record_index,
            "record_hash": raw.content_hash,
        }
    versions = await _analysis_versions(s)
    integrity = content_hash({"snapshot": snap, "provenance": {k: str(v) for k, v in prov.items()}, "analysis_version": versions})
    ev = EvidenceRecord(
        investigation_id=c.id,
        evidence_type=evidence_type,
        reference=reference,
        description=description,
        analysis_version=versions,
        snapshot=snap,
        integrity_hash=integrity,
        added_by=user.id,
        **prov,
    )
    s.add(ev)
    await s.flush()
    await audit.record(
        s,
        "case.evidence_attached",
        "investigation",
        str(c.id),
        actor_id=user.id,
        actor_email=user.email,
        details={"evidence_id": ev.id, "type": evidence_type, "reference": reference, "integrity_hash": integrity},
    )
    return ev


def _is_uuid(v: str) -> bool:
    try:
        uuid.UUID(v)
        return True
    except ValueError:
        return False


async def verify_evidence(s: AsyncSession, ev: EvidenceRecord) -> dict[str, Any]:
    prov = {
        k: getattr(ev, k)
        for k in (
            "txid",
            "block_hash",
            "source_dataset_id",
            "source_file_id",
            "source_file_sha256",
            "raw_record_id",
            "record_hash",
        )
        if getattr(ev, k) is not None
    }
    recomputed = content_hash(
        {"snapshot": ev.snapshot, "provenance": {k: str(v) for k, v in prov.items()}, "analysis_version": ev.analysis_version}
    )
    checks: dict[str, Any] = {"integrity_hash_matches": recomputed == ev.integrity_hash}
    if ev.raw_record_id:
        raw = await s.get(RawRecord, ev.raw_record_id)
        checks["raw_record_hash_matches"] = bool(raw and raw.content_hash == ev.record_hash)
    if ev.source_file_id:
        df = await s.get(DatasetFile, ev.source_file_id)
        p = Path(df.storage_path) if df else None
        checks["source_file_present"] = bool(p and p.exists())
        checks["source_file_sha256_matches"] = bool(p and p.exists() and file_sha256(p) == ev.source_file_sha256)
    checks["verified"] = all(v for v in checks.values() if isinstance(v, bool))
    checks["verified_at"] = datetime.now(UTC).isoformat()
    return checks
