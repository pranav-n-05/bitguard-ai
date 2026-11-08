"""Probabilistic address clustering. Clusters are investigative aids, never confirmed entities."""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from sklearn.cluster import DBSCAN
from sklearn.preprocessing import RobustScaler

from app.analytics.loader import Tx, coinjoin_like

LIMITS = {
    "common_input": (
        "Common-input-ownership heuristic: addresses co-spent in one transaction are often controlled by one wallet, but "
        "CoinJoin, PayJoin, custodial services and collaborative transactions break this assumption. CoinJoin-like "
        "transactions were excluded; undetected collaborative transactions may still merge unrelated addresses."
    ),
    "change_output": (
        "Change-output heuristic: an output is guessed to be change when it matches the input script type, has a "
        "non-round value and is a new address. Wallets that randomise these properties defeat the heuristic."
    ),
    "behavioural": (
        "Behavioural similarity only: addresses with similar activity statistics. Similar behaviour does not imply "
        "common ownership or any relationship."
    ),
}


class UnionFind:
    def __init__(self) -> None:
        self.p: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


@dataclass
class Cluster:
    method: str
    members: dict[str, float]  # address -> link confidence
    evidence: dict[str, Any]
    confidence: float
    evidence_txids: dict[str, list[str]] = field(default_factory=dict)


def _link_conf(n_support: int, base: float) -> float:
    return round(min(0.95, 1 - (1 - base) ** n_support), 3)


def common_input_clusters(txs: list[Tx], max_inputs: int = 100) -> tuple[list[Cluster], int]:
    uf = UnionFind()
    support: Counter[str] = Counter()
    ev: dict[str, list[str]] = defaultdict(list)
    excluded = 0
    for tx in txs:
        ins = sorted({a for a, _, _ in tx.inputs})
        if len(ins) < 2:
            continue
        if coinjoin_like(tx) or len(ins) > max_inputs:
            excluded += 1
            continue
        for a in ins[1:]:
            uf.union(ins[0], a)
        for a in ins:
            support[a] += 1
            if len(ev[a]) < 20:
                ev[a].append(tx.txid)
    groups: dict[str, list[str]] = defaultdict(list)
    for a in list(uf.p):
        groups[uf.find(a)].append(a)
    clusters = []
    for members in groups.values():
        if len(members) < 2:
            continue
        conf = {a: _link_conf(support[a], 0.55) for a in members}
        clusters.append(
            Cluster(
                "common_input",
                conf,
                {"co_spend_transactions": len({t for a in members for t in ev[a]})},
                round(float(np.mean(list(conf.values()))), 3),
                {a: ev[a] for a in members},
            )
        )
    return clusters, excluded


def change_output_links(txs: list[Tx]) -> list[tuple[str, str, float, str]]:
    """Return (input_address, change_address, confidence, txid) guesses."""
    seen: set[str] = set()
    links = []
    for tx in txs:
        if len(tx.outputs) == 2 and not coinjoin_like(tx):
            in_types = {st for _, _, st in tx.inputs}
            cands = []
            for a, v, st in tx.outputs:
                score = 0.0
                if len(in_types) == 1 and st in in_types:
                    score += 0.3
                if v % 100_000 != 0:
                    score += 0.2
                if a not in seen:
                    score += 0.2
                cands.append((score, a))
            cands.sort(reverse=True)
            if cands[0][0] >= 0.5 and cands[0][0] - cands[1][0] >= 0.2:
                links.append((tx.inputs[0][0], cands[0][1], round(min(0.7, cands[0][0]), 2), tx.txid))
        for a, _, _ in tx.inputs + tx.outputs:
            seen.add(a)
    return links


def change_output_clusters(txs: list[Tx]) -> list[Cluster]:
    uf = UnionFind()
    conf: dict[str, float] = {}
    ev: dict[str, list[str]] = defaultdict(list)
    for src, chg, c, txid in change_output_links(txs):
        uf.union(src, chg)
        conf[chg] = max(conf.get(chg, 0), c)
        conf.setdefault(src, c)
        ev[chg].append(txid)
        ev[src].append(txid)
    groups: dict[str, list[str]] = defaultdict(list)
    for a in list(uf.p):
        groups[uf.find(a)].append(a)
    out = []
    for m in groups.values():
        if len(m) >= 2:
            members = {a: conf.get(a, 0.4) for a in m}
            out.append(
                Cluster(
                    "change_output",
                    members,
                    {"change_links": sum(len(ev[a]) for a in m) // 2},
                    round(float(np.mean(list(members.values()))) * 0.8, 3),
                    {a: ev[a][:20] for a in m},
                )
            )
    return out


BEHAVIOUR_KEYS = [
    "tx_count",
    "tx_per_day",
    "unique_counterparties",
    "graph_in_degree",
    "graph_out_degree",
    "ip_diversity",
    "max_chain_depth",
]


def behavioural_clusters(addr_features: dict[str, dict[str, Any]], min_tx: int = 3, seed: int = 0) -> list[Cluster]:
    keys = [a for a, f in sorted(addr_features.items()) if f.get("tx_count", 0) >= min_tx]
    if len(keys) < 10:
        return []
    x = np.array([[float(addr_features[a].get(k) or 0.0) for k in BEHAVIOUR_KEYS] for a in keys])
    x = RobustScaler().fit_transform(np.log1p(np.clip(x, 0, None)))
    labels = DBSCAN(eps=0.15, min_samples=5).fit_predict(x)
    groups: dict[int, list[str]] = defaultdict(list)
    for a, lab in zip(keys, labels, strict=True):
        if lab >= 0:
            groups[int(lab)].append(a)
    out = []
    for lab, m in groups.items():
        if 2 <= len(m) <= 500:
            centroid = x[[keys.index(a) for a in m]].mean(axis=0)
            out.append(
                Cluster(
                    "behavioural",
                    dict.fromkeys(m, 0.3),
                    {"dbscan_label": lab, "centroid": dict(zip(BEHAVIOUR_KEYS, map(float, centroid), strict=True))},
                    0.3,
                )
            )
    _ = seed
    return out
