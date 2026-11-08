"""Load the canonical blockchain + network layer into memory for batch analytics.

Order is deterministic: (first_seen_at, id). All amounts stay integer satoshis.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import NetworkObservation, Transaction, TransactionInput, TransactionOutput


@dataclass
class Obs:
    id: int
    at: datetime
    src_ip: str
    dst_ip: str
    src_port: int
    dst_port: int
    protocol: str | None
    asn: int | None
    country: str | None


@dataclass
class Tx:
    id: int
    txid: str
    t: datetime
    fee: int
    vsize: int | None
    block_height: int | None
    script_type: str | None
    inputs: list[tuple[str, int, str | None]] = field(default_factory=list)
    outputs: list[tuple[str, int, str | None]] = field(default_factory=list)
    obs: list[Obs] = field(default_factory=list)

    @property
    def total_in(self) -> int:
        return sum(a for _, a, _ in self.inputs)

    @property
    def total_out(self) -> int:
        return sum(a for _, a, _ in self.outputs)

    @property
    def first_obs(self) -> Obs | None:
        return self.obs[0] if self.obs else None


async def load_transactions(s: AsyncSession) -> list[Tx]:
    txs: dict[int, Tx] = {}
    rows = await s.execute(
        select(
            Transaction.id,
            Transaction.txid,
            Transaction.first_seen_at,
            Transaction.fee_sat,
            Transaction.vsize,
            Transaction.block_height,
            Transaction.script_type,
        ).order_by(Transaction.first_seen_at, Transaction.id)
    )
    for r in rows:
        txs[r.id] = Tx(r.id, r.txid, r.first_seen_at, r.fee_sat, r.vsize, r.block_height, r.script_type)
    ins: dict[int, list[tuple[int, str, int, str | None]]] = defaultdict(list)
    for r in await s.execute(
        select(
            TransactionInput.transaction_id,
            TransactionInput.position,
            TransactionInput.address,
            TransactionInput.amount_sat,
            TransactionInput.script_type,
        )
    ):
        ins[r.transaction_id].append((r.position, r.address, r.amount_sat, r.script_type))
    outs: dict[int, list[tuple[int, str, int, str | None]]] = defaultdict(list)
    for r in await s.execute(
        select(
            TransactionOutput.transaction_id,
            TransactionOutput.position,
            TransactionOutput.address,
            TransactionOutput.amount_sat,
            TransactionOutput.script_type,
        )
    ):
        outs[r.transaction_id].append((r.position, r.address, r.amount_sat, r.script_type))
    for tid, tx in txs.items():
        tx.inputs = [(a, v, st) for _, a, v, st in sorted(ins[tid])]
        tx.outputs = [(a, v, st) for _, a, v, st in sorted(outs[tid])]
    for r in await s.execute(
        select(NetworkObservation)
        .where(NetworkObservation.transaction_id.is_not(None))
        .order_by(NetworkObservation.observed_at, NetworkObservation.id)
    ):
        o = r[0]
        target = txs.get(o.transaction_id)
        if target is not None:
            target.obs.append(
                Obs(o.id, o.observed_at, str(o.src_ip), str(o.dst_ip), o.src_port, o.dst_port, o.protocol, o.asn, o.geo_country)
            )
    return list(txs.values())


def coinjoin_like(tx: Tx) -> bool:
    """Equal-denomination multi-party structure. Treated as a privacy pattern, NOT as suspicious."""
    if len(tx.inputs) < 3 or len(tx.outputs) < 3:
        return False
    counts: dict[int, int] = defaultdict(int)
    for _, v, _ in tx.outputs:
        counts[v] += 1
    top = max(counts.values())
    distinct_inputs = len({a for a, _, _ in tx.inputs})
    return top >= 3 and distinct_inputs >= 3 and top >= len(tx.outputs) // 3
