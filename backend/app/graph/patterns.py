"""Structural pattern detection over the Address -> Tx -> Address bipartite graph.

Linkage between transactions is address-level ("an output address later appears as an input"),
because the source data does not carry outpoint (prevout) references. This is weaker than UTXO
linkage and is stated in every detection's limitations.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import networkx as nx

from app.analytics.loader import Tx, coinjoin_like

ADDR_LINK_LIMITATION = (
    "Transactions are linked when an output address later appears as an input (address-level linkage; the dataset "
    "has no outpoint references). Shared or reused addresses can create links between unrelated payments."
)


@dataclass
class PatternConfig:
    fan_out_min: int = 20
    fan_in_min: int = 15
    peel_min_hops: int = 5
    peel_max_ratio: float = 0.2
    peel_max_gap: timedelta = timedelta(hours=6)
    layer_min_hops: int = 4
    layer_max_gap: timedelta = timedelta(minutes=30)
    cycle_max_len: int = 6
    cycle_max_span: timedelta = timedelta(days=7)
    betweenness_k: int = 400
    seed: int = 1337


@dataclass
class Detection:
    pattern: str
    anchor_txid: str | None
    txids: list[str]
    addresses: list[str]
    metrics: dict[str, Any]
    confidence: float
    explanation: str
    limitations: str
    window_start: datetime | None = None
    window_end: datetime | None = None


@dataclass
class GraphMetrics:
    component_size: dict[str, int] = field(default_factory=dict)
    betweenness: dict[str, float] = field(default_factory=dict)
    degree: dict[str, int] = field(default_factory=dict)


def _spenders(txs: list[Tx]) -> dict[str, list[Tx]]:
    m: dict[str, list[Tx]] = defaultdict(list)
    for tx in txs:
        for a in {a for a, _, _ in tx.inputs}:
            m[a].append(tx)
    return m


def _next_spend(spenders: dict[str, list[Tx]], addr: str, after: Tx, max_gap: timedelta) -> Tx | None:
    for cand in spenders.get(addr, []):
        if cand.t >= after.t and cand.txid != after.txid and cand.t - after.t <= max_gap:
            return cand
    return None


def detect_patterns(txs: list[Tx], cfg: PatternConfig | None = None) -> list[Detection]:
    cfg = cfg or PatternConfig()
    out: list[Detection] = []
    spenders = _spenders(txs)

    for tx in txs:
        if coinjoin_like(tx):
            continue  # privacy structure: never reported as fan-in/fan-out
        n_out, n_in = len({a for a, _, _ in tx.outputs}), len({a for a, _, _ in tx.inputs})
        if n_out >= cfg.fan_out_min and n_in <= 3:
            vals = [v for _, v, _ in tx.outputs]
            spread = (max(vals) - min(vals)) / max(vals) if vals else 1.0
            out.append(
                Detection(
                    "high_fan_out",
                    tx.txid,
                    [tx.txid],
                    [a for a, _, _ in tx.inputs] + [a for a, _, _ in tx.outputs],
                    {"outputs": n_out, "inputs": n_in, "value_spread": round(spread, 4), "total_output_sat": tx.total_out},
                    round(min(0.9, 0.5 + n_out / 100), 3),
                    f"{n_in} input address(es) paid {n_out} distinct outputs in one transaction"
                    + (" with near-identical values (possible splitting)." if spread < 0.05 else "."),
                    "Exchanges and payroll/batch payouts legitimately produce high fan-out.",
                    tx.t,
                    tx.t,
                )
            )
        if n_in >= cfg.fan_in_min and n_out <= 2:
            out.append(
                Detection(
                    "high_fan_in",
                    tx.txid,
                    [tx.txid],
                    [a for a, _, _ in tx.inputs] + [a for a, _, _ in tx.outputs],
                    {"inputs": n_in, "outputs": n_out, "total_input_sat": tx.total_in},
                    round(min(0.9, 0.5 + n_in / 80), 3),
                    f"{n_in} input addresses consolidated into {n_out} output(s).",
                    "Wallet UTXO consolidation is routine; common-input does not prove common ownership.",
                    tx.t,
                    tx.t,
                )
            )

    # Peel chains: 2-output txs where a small output peels off and the large remainder is spent next.
    used: set[str] = set()
    for tx in txs:
        if tx.txid in used or len(tx.outputs) != 2 or len(tx.inputs) != 1:
            continue
        chain, cur = [tx], tx
        while True:
            outs = sorted(cur.outputs, key=lambda o: o[1])
            small, big = outs[0], outs[1]
            if big[1] == 0 or small[1] / big[1] > cfg.peel_max_ratio:
                break
            nxt = _next_spend(spenders, big[0], cur, cfg.peel_max_gap)
            if nxt is None or len(nxt.outputs) != 2 or len(nxt.inputs) != 1:
                break
            chain.append(nxt)
            cur = nxt
        if len(chain) >= cfg.peel_min_hops:
            used.update(t.txid for t in chain)
            addrs = sorted({a for t in chain for a, _, _ in t.inputs + t.outputs})
            peeled = sum(min(v for _, v, _ in t.outputs) for t in chain)
            out.append(
                Detection(
                    "peel_chain",
                    chain[0].txid,
                    [t.txid for t in chain],
                    addrs,
                    {
                        "hops": len(chain),
                        "peeled_total_sat": peeled,
                        "start_value_sat": chain[0].total_in,
                        "duration_minutes": round((chain[-1].t - chain[0].t).total_seconds() / 60, 1),
                    },
                    round(min(0.85, 0.4 + 0.05 * len(chain)), 3),
                    f"Chain of {len(chain)} transactions each peeling a small output while the remainder moves to a new address.",
                    ADDR_LINK_LIMITATION + " Ordinary change-spending can resemble a short peel chain.",
                    chain[0].t,
                    chain[-1].t,
                )
            )

    # Layering: rapid multi-hop movement through fresh addresses.
    first_seen: dict[str, datetime] = {}
    for tx in txs:
        for a, _, _ in tx.inputs + tx.outputs:
            first_seen.setdefault(a, tx.t)
    for tx in txs:
        if tx.txid in used:
            continue
        chain, cur = [tx], tx
        while len(chain) < 50:
            nxt = None
            for a, _, _ in sorted(cur.outputs, key=lambda o: -o[1]):
                cand = _next_spend(spenders, a, cur, cfg.layer_max_gap)
                if cand and first_seen.get(a) == cur.t:
                    nxt = cand
                    break
            if nxt is None or nxt.txid in used:
                break
            chain.append(nxt)
            cur = nxt
        if len(chain) >= cfg.layer_min_hops:
            used.update(t.txid for t in chain)
            mins = (chain[-1].t - chain[0].t).total_seconds() / 60
            out.append(
                Detection(
                    "rapid_layering",
                    chain[0].txid,
                    [t.txid for t in chain],
                    sorted({a for t in chain for a, _, _ in t.inputs + t.outputs}),
                    {"hops": len(chain), "duration_minutes": round(mins, 1), "value_sat": chain[0].total_in},
                    round(min(0.85, 0.35 + 0.08 * len(chain)), 3),
                    f"Funds moved through {len(chain)} hops of newly created addresses within {mins:.0f} minutes.",
                    ADDR_LINK_LIMITATION + " Automated wallet sweeps can also produce rapid hops.",
                    chain[0].t,
                    chain[-1].t,
                )
            )

    # Temporal cycles: follow value forward (each received output -> the next transaction spending that address,
    # time-ordered, within cycle_max_span) and report paths that return to the starting address.
    seen_cycles: set[frozenset[str]] = set()
    for t0 in txs:
        if coinjoin_like(t0) or len(t0.inputs) > 5:
            continue
        starts = {a for a, _, _ in t0.inputs}
        deadline = t0.t + cfg.cycle_max_span
        stack: list[tuple[Tx, list[Tx], list[str]]] = [(t0, [t0], [t0.inputs[0][0]])]
        while stack:
            cur, path, addrs = stack.pop()
            if len(path) > cfg.cycle_max_len:
                continue
            for o, _, _ in cur.outputs:
                if o in {a for a, _, _ in cur.inputs}:
                    continue  # self-change is not a hop
                if o in starts and len(path) >= 3:
                    key = frozenset(t.txid for t in path)
                    if key not in seen_cycles:
                        seen_cycles.add(key)
                        span = path[-1].t - path[0].t
                        ring = [*addrs[:1], *addrs[1:]]
                        out.append(
                            Detection(
                                "circular_flow",
                                path[0].txid,
                                [t.txid for t in path],
                                ring,
                                {"cycle_length": len(path), "span_hours": round(span.total_seconds() / 3600, 2)},
                                round(min(0.85, 0.5 + 0.05 * len(path)), 3),
                                f"Value returns to its starting address through a {len(path)}-hop cycle within "
                                f"{span.total_seconds() / 3600:.1f} hours.",
                                ADDR_LINK_LIMITATION + " Cycles can arise from address reuse between related services.",
                                path[0].t,
                                path[-1].t,
                            )
                        )
                    continue
                nxt = _next_spend(spenders, o, cur, deadline - cur.t)
                if nxt is not None and nxt.txid not in {t.txid for t in path} and len(path) < cfg.cycle_max_len:
                    stack.append((nxt, [*path, nxt], [*addrs, o]))
    return out


def graph_metrics(txs: list[Tx], cfg: PatternConfig | None = None) -> GraphMetrics:
    """Component sizes, degree and *sampled* betweenness (k-sample, fixed seed) on the bipartite graph."""
    cfg = cfg or PatternConfig()
    g = nx.Graph()
    for tx in txs:
        t = f"tx:{tx.txid}"
        for a, _, _ in tx.inputs + tx.outputs:
            g.add_edge(f"a:{a}", t)
    m = GraphMetrics()
    for comp in nx.connected_components(g):
        n_addr = sum(1 for n in comp if n.startswith("a:"))
        for n in comp:
            if n.startswith("a:"):
                m.component_size[n[2:]] = n_addr
    for n, d in g.degree():
        if n.startswith("a:"):
            m.degree[n[2:]] = d
    if g.number_of_nodes() > 2:
        k = min(cfg.betweenness_k, g.number_of_nodes())
        bc = nx.betweenness_centrality(g, k=k, seed=cfg.seed, normalized=True)
        m.betweenness = {n[2:]: round(v, 8) for n, v in bc.items() if n.startswith("a:")}
    return m
