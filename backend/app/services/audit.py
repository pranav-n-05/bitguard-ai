"""Append-only, hash-chained audit log writer and verifier."""

import uuid
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.hashing import chain_hash
from app.models import AuditLog

_LOCK_KEY = 0x6269_7467  # "bitg" advisory lock serialises chain appends


async def record(
    session: AsyncSession,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    *,
    actor_id: uuid.UUID | None = None,
    actor_email: str | None = None,
    details: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> AuditLog:
    await session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _LOCK_KEY})
    last = (await session.execute(select(AuditLog.seq, AuditLog.entry_hash).order_by(AuditLog.seq.desc()).limit(1))).first()
    seq = (last.seq + 1) if last else 1
    prev = last.entry_hash if last else None
    payload = {
        "seq": seq,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "actor_id": str(actor_id) if actor_id else None,
        "details": details or {},
    }
    entry = AuditLog(
        seq=seq,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_id=actor_id,
        actor_email=actor_email,
        details=details or {},
        request_id=request_id,
        prev_hash=prev,
        entry_hash=chain_hash(prev, payload),
    )
    session.add(entry)
    await session.flush()
    return entry


async def verify_chain(session: AsyncSession) -> tuple[bool, int, int | None]:
    """Returns (ok, entries_checked, first_bad_seq)."""
    prev: str | None = None
    n = 0
    for row in (await session.execute(select(AuditLog).order_by(AuditLog.seq))).scalars():
        payload = {
            "seq": row.seq,
            "action": row.action,
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
            "actor_id": str(row.actor_id) if row.actor_id else None,
            "details": row.details,
        }
        if row.prev_hash != prev or row.entry_hash != chain_hash(prev, payload):
            return False, n, row.seq
        prev = row.entry_hash
        n += 1
    return True, n, None
