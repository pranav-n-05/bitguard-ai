"""Bounded, on-demand graph queries against the database, returned as Cytoscape.js elements.

Model: bipartite Address -[INPUT_OF]-> Transaction -[OUTPUT_OF]-> Address (multi-input/multi-output is
never collapsed into address-to-address edges), plus IP/ASN/Country/Cluster/Case context nodes.
"""

import itertools
from collections import deque
from datetime import datetime
from typing import Any

import networkx as nx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AddressCluster,
    ClusterMembership,
    InvestigationAddress,
    InvestigationTransaction,
    NetworkObservation,
    RiskAssessment,
    Transaction,
    TransactionInput,
    TransactionOutput,
)

MAX_NODES_HARD = 2000


class GraphBuilder:
    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: dict[str, dict[str, Any]] = {}
        self.truncated = False

    def node(self, nid: str, ntype: str, label: str, **data: Any) -> None:
        if nid not in self.nodes:
            self.nodes[nid] = {"id": nid, "type": ntype, "label": label, **data}

    def edge(self, src: str, dst: str, etype: str, **data: Any) -> None:
        eid = f"{etype}:{src}->{dst}:{data.get('position', '')}"
        self.edges.setdefault(eid, {"id": eid, "source": src, "target": dst, "type": etype, **data})

    def elements(self) -> dict[str, Any]:
        return {
            "nodes": [{"data": n} for n in self.nodes.values()],
            "edges": [{"data": e} for e in self.edges.values()],
            "truncated": self.truncated,
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
        }


def _short(s: str) -> str:
    return f"{s[:8]}…{s[-6:]}" if len(s) > 18 else s


async def _add_txs(s: AsyncSession, g: GraphBuilder, tx_ids: list[int]) -> set[str]:
    """Add transactions with all their inputs/outputs; return addresses touched."""
    if not tx_ids:
        return set()
    addrs: set[str] = set()
    for t in (await s.execute(select(Transaction).where(Transaction.id.in_(tx_ids)))).scalars():
        g.node(
            f"tx:{t.txid}",
            "transaction",
            _short(t.txid),
            txid=t.txid,
            time=t.first_seen_at.isoformat(),
            value_sat=t.total_output_sat,
            fee_sat=t.fee_sat,
            inputs=t.input_count,
            outputs=t.output_count,
        )
    id2tx = {t.id: t.txid for t in (await s.execute(select(Transaction.id, Transaction.txid).where(Transaction.id.in_(tx_ids))))}
    for r in await s.execute(select(TransactionInput).where(TransactionInput.transaction_id.in_(tx_ids))):
        i = r[0]
        g.node(f"addr:{i.address}", "address", _short(i.address), address=i.address)
        g.edge(f"addr:{i.address}", f"tx:{id2tx[i.transaction_id]}", "INPUT_OF", amount_sat=i.amount_sat, position=i.position)
        addrs.add(i.address)
    for r in await s.execute(select(TransactionOutput).where(TransactionOutput.transaction_id.in_(tx_ids))):
        o = r[0]
        g.node(f"addr:{o.address}", "address", _short(o.address), address=o.address)
        g.edge(f"tx:{id2tx[o.transaction_id]}", f"addr:{o.address}", "OUTPUT_OF", amount_sat=o.amount_sat, position=o.position)
        addrs.add(o.address)
    return addrs


async def _tx_ids_for_addresses(
    s: AsyncSession, addrs: set[str], start: datetime | None, end: datetime | None, limit: int
) -> list[int]:
    q_in = select(TransactionInput.transaction_id).where(TransactionInput.address.in_(addrs))
    q_out = select(TransactionOutput.transaction_id).where(TransactionOutput.address.in_(addrs))
    q = select(Transaction.id).where(Transaction.id.in_(q_in.union(q_out)))
    if start:
        q = q.where(Transaction.first_seen_at >= start)
    if end:
        q = q.where(Transaction.first_seen_at <= end)
    return list((await s.execute(q.order_by(Transaction.first_seen_at).limit(limit))).scalars())


async def _context(s: AsyncSession, g: GraphBuilder, include_network: bool) -> None:
    txids = [n["txid"] for n in g.nodes.values() if n["type"] == "transaction"]
    addrs = [n["address"] for n in g.nodes.values() if n["type"] == "address"]
    risk = {
        (row1.entity_type, row1.entity_key): row1
        for row1 in (
            await s.execute(
                select(RiskAssessment.entity_type, RiskAssessment.entity_key, RiskAssessment.score, RiskAssessment.band).where(
                    RiskAssessment.is_current.is_(True), RiskAssessment.entity_key.in_(txids + addrs)
                )
            )
        )
    }
    for n in g.nodes.values():
        key = ("transaction", n.get("txid")) if n["type"] == "transaction" else ("address", n.get("address"))
        if key in risk:
            n["risk_score"], n["risk_band"] = risk[key].score, risk[key].band.value
    if include_network and txids:
        for row2 in await s.execute(
            select(
                NetworkObservation.id,
                NetworkObservation.txid,
                NetworkObservation.src_ip,
                NetworkObservation.asn,
                NetworkObservation.geo_country,
                NetworkObservation.observed_at,
            )
            .where(NetworkObservation.txid.in_(txids))
            .order_by(NetworkObservation.observed_at)
        ):
            ip = str(row2.src_ip)
            g.node(f"ip:{ip}", "ip", ip, ip=ip)
            g.edge(
                f"tx:{row2.txid}", f"ip:{ip}", "OBSERVED_FROM", observation_id=row2.id, observed_at=row2.observed_at.isoformat()
            )
            if row2.asn is not None:
                g.node(f"asn:{row2.asn}", "asn", f"AS{row2.asn}", asn=row2.asn)
                g.edge(f"ip:{ip}", f"asn:{row2.asn}", "ASSOCIATED_WITH")
            if row2.geo_country:
                g.node(f"country:{row2.geo_country}", "country", row2.geo_country, country=row2.geo_country)
                g.edge(f"ip:{ip}", f"country:{row2.geo_country}", "ASSOCIATED_WITH")
    if addrs:
        for row3 in await s.execute(
            select(
                ClusterMembership.address,
                AddressCluster.id,
                AddressCluster.method,
                AddressCluster.confidence,
                AddressCluster.size,
            )
            .join(AddressCluster, AddressCluster.id == ClusterMembership.cluster_id)
            .where(ClusterMembership.address.in_(addrs), AddressCluster.method != "behavioural")
        ):
            cid = f"cluster:{row3.id}"
            g.node(
                cid,
                "cluster",
                f"{row3.method} ({row3.size})",
                cluster_id=str(row3.id),
                method=row3.method,
                confidence=row3.confidence,
            )
            g.edge(f"addr:{row3.address}", cid, "PART_OF_CLUSTER", confidence=row3.confidence)
        for row4 in await s.execute(
            select(InvestigationAddress.address, InvestigationAddress.investigation_id).where(
                InvestigationAddress.address.in_(addrs)
            )
        ):
            g.node(f"case:{row4.investigation_id}", "case", "Case", case_id=str(row4.investigation_id))
            g.edge(f"addr:{row4.address}", f"case:{row4.investigation_id}", "LINKED_TO_CASE")
    if txids:
        for row5 in await s.execute(
            select(InvestigationTransaction.txid, InvestigationTransaction.investigation_id).where(
                InvestigationTransaction.txid.in_(txids)
            )
        ):
            g.node(f"case:{row5.investigation_id}", "case", "Case", case_id=str(row5.investigation_id))
            g.edge(f"tx:{row5.txid}", f"case:{row5.investigation_id}", "LINKED_TO_CASE")


async def neighbourhood(
    s: AsyncSession,
    *,
    address: str | None = None,
    txid: str | None = None,
    hops: int = 1,
    max_nodes: int = 300,
    start: datetime | None = None,
    end: datetime | None = None,
    include_network: bool = True,
) -> dict[str, Any]:
    """Multi-hop expansion. One hop = address -> its transactions -> their counterpart addresses."""
    max_nodes = min(max_nodes, MAX_NODES_HARD)
    g = GraphBuilder()
    frontier: set[str] = set()
    if txid:
        t = (await s.execute(select(Transaction.id).where(Transaction.txid == txid))).scalar_one_or_none()
        if t is None:
            return g.elements()
        frontier = await _add_txs(s, g, [t])
    elif address:
        frontier = {address}
    seen_addr: set[str] = set()
    for _ in range(hops if address else max(hops - 1, 0)):
        frontier -= seen_addr
        if not frontier:
            break
        seen_addr |= frontier
        budget = max_nodes - len(g.nodes)
        if budget <= 0:
            g.truncated = True
            break
        ids = await _tx_ids_for_addresses(s, frontier, start, end, limit=max(budget // 3, 1))
        if len(ids) >= max(budget // 3, 1):
            g.truncated = True
        frontier = await _add_txs(s, g, ids)
    if address:
        g.node(f"addr:{address}", "address", _short(address), address=address)
        g.nodes[f"addr:{address}"]["focus"] = True
    if txid and f"tx:{txid}" in g.nodes:
        g.nodes[f"tx:{txid}"]["focus"] = True
    await _context(s, g, include_network)
    return g.elements()


def to_networkx(elements: dict[str, Any]) -> nx.MultiDiGraph:
    g = nx.MultiDiGraph()
    for n in elements["nodes"]:
        g.add_node(n["data"]["id"], **n["data"])
    for e in elements["edges"]:
        g.add_edge(e["data"]["source"], e["data"]["target"], **e["data"])
    return g


async def shortest_path(s: AsyncSession, src: str, dst: str, max_hops: int = 4, max_nodes: int = 1500) -> dict[str, Any]:
    """Bidirectional bounded expansion then shortest path over the bipartite graph (direction ignored)."""
    a = await neighbourhood(s, address=src, hops=max_hops // 2 + max_hops % 2, max_nodes=max_nodes // 2, include_network=False)
    b = await neighbourhood(s, address=dst, hops=max_hops // 2, max_nodes=max_nodes // 2, include_network=False)
    g = nx.compose(to_networkx(a), to_networkx(b)).to_undirected()
    try:
        path = nx.shortest_path(g, f"addr:{src}", f"addr:{dst}")
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return {
            "found": False,
            "path": [],
            "searched_nodes": g.number_of_nodes(),
            "truncated": a["truncated"] or b["truncated"],
            "max_hops": max_hops,
        }
    sub = GraphBuilder()
    for nid in path:
        sub.nodes[nid] = dict(g.nodes[nid])
    for x, y in itertools.pairwise(path):
        data = next(iter(g.get_edge_data(x, y).values()))
        sub.edges[data["id"]] = data
    return {"found": True, "path": path, "hops": sum(1 for n in path if n.startswith("tx:")), **sub.elements()}


async def trace_flow(
    s: AsyncSession, txid: str, direction: str = "forward", depth: int = 4, max_nodes: int = 400
) -> dict[str, Any]:
    """Follow value forward (outputs -> later spends) or backward (inputs -> earlier funding txs), time-ordered."""
    g = GraphBuilder()
    root = (await s.execute(select(Transaction).where(Transaction.txid == txid))).scalar_one_or_none()
    if root is None:
        return g.elements()
    queue: deque[tuple[int, datetime, int]] = deque([(root.id, root.first_seen_at, 0)])
    visited: set[int] = set()
    while queue and len(g.nodes) < max_nodes:
        tid, t, d = queue.popleft()
        if tid in visited:
            continue
        visited.add(tid)
        await _add_txs(s, g, [tid])
        if d >= depth:
            continue
        if direction == "forward":
            addrs = (
                (await s.execute(select(TransactionOutput.address).where(TransactionOutput.transaction_id == tid)))
                .scalars()
                .all()
            )
            q = (
                select(Transaction.id, Transaction.first_seen_at)
                .join(TransactionInput, TransactionInput.transaction_id == Transaction.id)
                .where(TransactionInput.address.in_(addrs), Transaction.first_seen_at >= t, Transaction.id != tid)
                .order_by(Transaction.first_seen_at)
                .limit(10)
            )
        else:
            addrs = (
                (await s.execute(select(TransactionInput.address).where(TransactionInput.transaction_id == tid))).scalars().all()
            )
            q = (
                select(Transaction.id, Transaction.first_seen_at)
                .join(TransactionOutput, TransactionOutput.transaction_id == Transaction.id)
                .where(TransactionOutput.address.in_(addrs), Transaction.first_seen_at <= t, Transaction.id != tid)
                .order_by(Transaction.first_seen_at.desc())
                .limit(10)
            )
        for r in await s.execute(q):
            queue.append((r.id, r.first_seen_at, d + 1))
    g.truncated = bool(queue)
    if f"tx:{txid}" in g.nodes:
        g.nodes[f"tx:{txid}"]["focus"] = True
    await _context(s, g, include_network=False)
    out = g.elements()
    out["limitations"] = (
        "Address-level tracing: a later transaction spending from the same address is assumed to spend these "
        "funds. Without outpoint references this can over-connect reused addresses."
    )
    return out
