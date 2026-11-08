"""Network-layer <-> blockchain-layer correlation.

Every indicator expresses *co-occurrence or timing correlation* between network observations and
transactions. None of them establishes that an IP owner controls an address.
"""

from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.analytics.loader import Tx

LIMITATION = (
    "Network co-occurrence/timing only. An IP observed relaying or first-announcing a transaction may be a relay node, "
    "VPN/NAT egress, shared host or wallet service; this does not identify who controls any address."
)
STANDARD_PORTS = {8333, 18333, 18444, 38333}


@dataclass
class CorrelationConfig:
    burst_window: timedelta = timedelta(minutes=10)
    burst_min_tx: int = 10
    wallet_ip_min_tx: int = 5
    asn_window: timedelta = timedelta(minutes=10)
    asn_min_tx: int = 15
    asn_ratio: float = 5.0


@dataclass
class Indicator:
    indicator_type: str
    entity_type: str
    entity_key: str
    window_start: datetime
    window_end: datetime
    strength: float
    confidence: float
    metrics: dict[str, Any]
    evidence_refs: dict[str, Any]


def ip_specificity(txs: list[Tx]) -> dict[str, float]:
    """Share of an IP's observations that are first sightings. Relay-like IPs (mostly re-broadcasting) score low."""
    first: Counter[str] = Counter()
    total: Counter[str] = Counter()
    for tx in txs:
        for j, o in enumerate(tx.obs):
            total[o.src_ip] += 1
            if j == 0:
                first[o.src_ip] += 1
    return {ip: first[ip] / n for ip, n in total.items()}


def correlate(txs: list[Tx], cfg: CorrelationConfig | None = None) -> list[Indicator]:
    cfg = cfg or CorrelationConfig()
    spec = ip_specificity(txs)
    out: list[Indicator] = []
    origin: dict[str, list[Tx]] = defaultdict(list)
    for tx in txs:
        if tx.first_obs:
            origin[tx.first_obs.src_ip].append(tx)

    # 1) Burst of first-sighted transactions from one source IP
    for ip, items in origin.items():
        win: deque[Tx] = deque()
        best: list[Tx] = []
        for tx in items:
            win.append(tx)
            while tx.t - win[0].t > cfg.burst_window:
                win.popleft()
            if len(win) > len(best):
                best = list(win)
        if len(best) >= cfg.burst_min_tx:
            days = max((items[-1].t - items[0].t).total_seconds() / 86400, 1.0)
            baseline = len(items) / days / (86400 / cfg.burst_window.total_seconds())
            ratio = len(best) / max(baseline, 1e-9)
            conf = round(min(0.95, spec.get(ip, 0) * (1 - 0.85 ** len(best))), 3)
            out.append(
                Indicator(
                    "ip_transaction_burst",
                    "ip",
                    ip,
                    best[0].t,
                    best[-1].t,
                    round(min(ratio / 50, 1.0), 3),
                    conf,
                    {
                        "tx_in_window": len(best),
                        "window_minutes": cfg.burst_window.total_seconds() / 60,
                        "baseline_per_window": round(baseline, 4),
                        "ratio_to_baseline": round(ratio, 1),
                        "ip_first_sighting_share": round(spec.get(ip, 0), 3),
                        "ip_total_first_sightings": len(items),
                    },
                    {"txids": [t.txid for t in best], "observation_ids": [t.first_obs.id for t in best if t.first_obs]},
                )
            )

    # 2) Repeated address <-> origin-IP co-occurrence
    pair: dict[tuple[str, str], list[Tx]] = defaultdict(list)
    for ip, items in origin.items():
        for tx in items:
            for a in {a for a, _, _ in tx.inputs}:
                pair[(a, ip)].append(tx)
    for (a, ip), items in pair.items():
        if len(items) >= cfg.wallet_ip_min_tx:
            k = len(items)
            conf = round(min(0.9, spec.get(ip, 0) * (1 - 0.6**k)), 3)
            out.append(
                Indicator(
                    "repeated_address_ip_cooccurrence",
                    "address",
                    a,
                    items[0].t,
                    items[-1].t,
                    round(min(k / 10, 1.0), 3),
                    conf,
                    {"ip": ip, "co_occurrences": k, "ip_first_sighting_share": round(spec.get(ip, 0), 3)},
                    {"txids": [t.txid for t in items], "observation_ids": [t.first_obs.id for t in items if t.first_obs]},
                )
            )

    # 3) ASN concentration within a short window, relative to that ASN's baseline
    by_asn: dict[int, list[Tx]] = defaultdict(list)
    for tx in txs:
        if tx.first_obs and tx.first_obs.asn is not None:
            by_asn[tx.first_obs.asn].append(tx)
    for asn, items in by_asn.items():
        days = max((items[-1].t - items[0].t).total_seconds() / 86400, 1.0)
        baseline = len(items) / days / (86400 / cfg.asn_window.total_seconds())
        awin: deque[Tx] = deque()
        best = []  # reset per ASN
        for tx in items:
            awin.append(tx)
            while tx.t - awin[0].t > cfg.asn_window:
                awin.popleft()
            if len(awin) > len(best):
                best = list(awin)
        ratio = len(best) / max(baseline, 1e-9)
        if len(best) >= cfg.asn_min_tx and ratio >= cfg.asn_ratio:
            out.append(
                Indicator(
                    "asn_window_concentration",
                    "asn",
                    str(asn),
                    best[0].t,
                    best[-1].t,
                    round(min(ratio / 50, 1.0), 3),
                    round(min(0.8, 1 - 0.9 ** len(best)) * 0.7, 3),
                    {
                        "tx_in_window": len(best),
                        "baseline_per_window": round(baseline, 4),
                        "ratio_to_baseline": round(ratio, 1),
                        "distinct_ips": len({t.first_obs.src_ip for t in best if t.first_obs}),
                    },
                    {"txids": [t.txid for t in best]},
                )
            )

    # 4) Non-standard P2P ports
    odd: dict[str, list[Tx]] = defaultdict(list)
    for tx in txs:
        for o in tx.obs[:1]:
            if o.dst_port not in STANDARD_PORTS:
                odd[o.src_ip].append(tx)
    for ip, items in odd.items():
        if len(items) >= 3:
            out.append(
                Indicator(
                    "nonstandard_port_usage",
                    "ip",
                    ip,
                    items[0].t,
                    items[-1].t,
                    round(min(len(items) / 20, 1.0), 3),
                    0.3,
                    {"count": len(items), "ports": sorted({o.dst_port for t in items for o in t.obs[:1]})},
                    {"txids": [t.txid for t in items]},
                )
            )
    return out
