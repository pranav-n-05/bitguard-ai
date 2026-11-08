"""Alert state machine, assignment, notes and analyst feedback."""

import uuid
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import InvalidStateError, NotFoundError, PermissionDeniedError
from app.models import Alert, AlertNote, EvaluationLabel, User
from app.models.base import AlertStatus as S
from app.services import audit

TRANSITIONS: dict[S, set[S]] = {
    S.new: {S.acknowledged, S.under_investigation, S.false_positive},
    S.acknowledged: {S.under_investigation, S.escalated, S.resolved, S.false_positive},
    S.under_investigation: {S.escalated, S.resolved, S.false_positive},
    S.escalated: {S.under_investigation, S.resolved, S.false_positive},
    S.resolved: {S.under_investigation},
    S.false_positive: {S.under_investigation},
}
NEEDS_RESOLVE_PERM = {S.escalated, S.resolved, S.false_positive}
CATEGORIES = {
    "unusual_transaction_amount",
    "unusual_transaction_frequency",
    "rapid_transaction_movement",
    "high_fan_in",
    "high_fan_out",
    "repeated_transaction_splitting",
    "unusual_consolidation",
    "suspicious_graph_pattern",
    "potential_layering_pattern",
    "circular_transaction_pattern",
    "unusual_wallet_behaviour",
    "high_anomaly_score",
    "new_unusual_transaction_cluster",
    "network_blockchain_correlation_anomaly",
}


async def get(s: AsyncSession, alert_id: uuid.UUID, lock: bool = False) -> Alert:
    a = await s.get(Alert, alert_id, with_for_update=lock)
    if a is None:
        raise NotFoundError("Alert not found")
    return a


async def transition(
    s: AsyncSession, alert: Alert, to: S, user: User, note: str | None = None, confirmed_suspicious: bool | None = None
) -> Alert:
    if to == alert.status:
        return alert
    if to not in TRANSITIONS[alert.status]:
        raise InvalidStateError(
            f"Cannot move alert from {alert.status.value} to {to.value}",
            extra={"allowed": sorted(t.value for t in TRANSITIONS[alert.status])},
        )
    perm = (
        "alert.resolve" if (to in NEEDS_RESOLVE_PERM or alert.status in (S.resolved, S.false_positive)) else "alert.acknowledge"
    )
    if perm not in user.permission_codes:
        raise PermissionDeniedError(f"Missing permission: {perm}")
    if to in (S.resolved, S.false_positive) and not (note and note.strip()):
        raise InvalidStateError("A resolution note is required")
    old = alert.status
    alert.status = to
    if to in (S.resolved, S.false_positive):
        alert.resolution_note = note
    if note:
        s.add(AlertNote(alert_id=alert.id, author_id=user.id, body=f"[{old.value} -> {to.value}] {note}"))
    if alert.txid and (to == S.false_positive or (to == S.resolved and confirmed_suspicious is not None)):
        label = "benign" if to == S.false_positive or confirmed_suspicious is False else "suspicious"
        st = pg_insert(EvaluationLabel).values(
            entity_type="transaction",
            entity_key=alert.txid,
            label=label,
            pattern=alert.category,
            source="analyst_feedback",
            created_by=user.id,
        )
        await s.execute(st.on_conflict_do_update(index_elements=["entity_type", "entity_key", "source"], set_={"label": label}))
    await audit.record(
        s,
        "alert.status_changed",
        "alert",
        str(alert.id),
        actor_id=user.id,
        actor_email=user.email,
        details={"from": old.value, "to": to.value, "note": note, "confirmed_suspicious": confirmed_suspicious},
    )
    return alert


async def assign(s: AsyncSession, alert: Alert, assignee: uuid.UUID | None, user: User) -> Alert:
    if assignee is not None:
        target = await s.get(User, assignee)
        if target is None or not target.is_active:
            raise NotFoundError("Assignee not found or inactive")
        if "alert.acknowledge" not in target.permission_codes:
            raise InvalidStateError("Assignee lacks permission to work alerts")
    old = alert.assigned_to
    alert.assigned_to = assignee
    await audit.record(
        s,
        "alert.assigned",
        "alert",
        str(alert.id),
        actor_id=user.id,
        actor_email=user.email,
        details={"from": str(old) if old else None, "to": str(assignee) if assignee else None},
    )
    return alert


async def add_note(s: AsyncSession, alert: Alert, body: str, user: User) -> AlertNote:
    n = AlertNote(alert_id=alert.id, author_id=user.id, body=body)
    s.add(n)
    await s.flush()
    await audit.record(
        s, "alert.note_added", "alert", str(alert.id), actor_id=user.id, actor_email=user.email, details={"note_id": n.id}
    )
    return n


def _unused(x: Any) -> None:
    return None
