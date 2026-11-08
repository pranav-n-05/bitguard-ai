"""Point-in-time feature engineering (leakage-safe).

Transactions are processed once in (first_seen_at, id) order. Each transaction's feature vector is
computed from state that only contains *earlier* transactions plus the transaction itself, so adding
future data can never change a past feature row. Network features for a transaction only use
observations within OBS_WINDOW of first sighting (the stated `as_of`).

Missing values are stored as None (JSON null) — never as zero — and the model layer adds explicit
missing-indicator columns.
"""

import math
import statistics
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.analytics.loader import Tx, coinjoin_like

SCHEMA_VERSION = "tx-v1"
ADDR_SCHEMA_VERSION = "addr-v1"
NET_SCHEMA_VERSION = "net-v1"
OBS_WINDOW = timedelta(seconds=60)
BURST_WINDOW = timedelta(minutes=10)
ROUND_UNIT = 100_000  # 0.001 BTC

TX_FEATURES = [
    "total_input_sat",
    "total_output_sat",
    "fee_sat",
    "fee_rate",
    "input_count",
    "output_count",
    "vsize",
    "value_imbalance",
    "output_value_cv",
    "max_equal_outputs",
    "repeated_output_values",
    "round_output_ratio",
    "fan_in",
    "fan_out",
    "secs_since_prev_related",
    "min_input_holding_secs",
    "chain_depth",
    "unique_counterparties",
    "output_address_reuse_ratio",
    "fresh_input_ratio",
    "graph_degree",
    "network_observation_count",
    "ip_diversity",
    "asn_diversity",
    "src_ip_tx_10m",
    "src_ip_burst_score",
    "src_ip_unique_addresses",
    "is_coinjoin_like",
]
# Features where only magnitude matters (log-scaled for the model).
LOG_FEATURES = {"total_input_sat", "total_output_sat", "fee_sat", "secs_since_prev_related", "min_input_holding_secs"}


@dataclass
class AddrState:
    first_seen: datetime
    last_seen: datetime
    tx_count: int = 0
    in_count: int = 0
    out_count: int = 0
    received: int = 0
    spent: int = 0
    max_value: int = 0
    counterparties: set[str] = field(default_factory=set)
    in_neighbours: set[str] = field(default_factory=set)
    out_neighbours: set[str] = field(default_factory=set)
    intervals_sum: float = 0.0
    last_received: datetime | None = None
    depth: int = 0
    ips: set[str] = field(default_factory=set)
    asns: set[int] = field(default_factory=set)
    txids: list[str] = field(default_factory=list)


@dataclass
class NetState:
    times: deque[datetime] = field(default_factory=deque)
    all_times: list[datetime] = field(default_factory=list)
    txids: set[str] = field(default_factory=set)
    addresses: Counter[str] = field(default_factory=Counter)
    value: int = 0
    ports: set[int] = field(default_factory=set)
    asns: set[int] = field(default_factory=set)
    countries: set[str] = field(default_factory=set)
    ips: set[str] = field(default_factory=set)
    max_burst: int = 0


def _cv(values: list[int]) -> float | None:
    if len(values) < 2:
        return None
    m = statistics.fmean(values)
    return statistics.pstdev(values) / m if m else None


@dataclass
class FeatureResult:
    tx: dict[str, dict[str, Any]]  # txid -> features (+ "_as_of")
    addresses: dict[str, dict[str, Any]]
    network: dict[tuple[str, str], dict[str, Any]]
    cutoff: datetime | None


def compute_features(txs: list[Tx]) -> FeatureResult:
    addr: dict[str, AddrState] = {}
    ips: dict[str, NetState] = defaultdict(NetState)
    asns: dict[str, NetState] = defaultdict(NetState)
    countries: dict[str, NetState] = defaultdict(NetState)
    tx_out: dict[str, dict[str, Any]] = {}
    last_t: datetime | None = None

    for tx in txs:
        t = tx.t
        last_t = t
        in_addrs = [a for a, _, _ in tx.inputs]
        out_addrs = [a for a, _, _ in tx.outputs]
        uniq_in, uniq_out = set(in_addrs), set(out_addrs)
        outs = [v for _, v, _ in tx.outputs]
        total_in, total_out = tx.total_in, tx.total_out
        eq = Counter(outs)
        known_inputs = [addr[a] for a in uniq_in if a in addr]
        prev_times = [s.last_seen for s in known_inputs]
        holding = [(t - s.last_received).total_seconds() for s in known_inputs if s.last_received]
        fresh = sum(1 for a in uniq_in if a not in addr or (t - addr[a].first_seen) < timedelta(hours=1))
        depth = 1 + max((s.depth for s in known_inputs), default=0)
        early_obs = [o for o in tx.obs if o.at - t <= OBS_WINDOW]
        first = tx.first_obs
        src_ns = ips[first.src_ip] if first else None
        if src_ns is not None:
            while src_ns.times and t - src_ns.times[0] > BURST_WINDOW:
                src_ns.times.popleft()
            prior_10m = len(src_ns.times)
            span_days = max((t - src_ns.all_times[0]).total_seconds() / 86400, 1.0) if src_ns.all_times else 1.0
            expected_10m = len(src_ns.all_times) / span_days / 144.0
            burst = (prior_10m + 1) / (expected_10m + 1)
        f: dict[str, Any] = {
            "total_input_sat": total_in,
            "total_output_sat": total_out,
            "fee_sat": tx.fee,
            "fee_rate": (tx.fee / tx.vsize) if tx.vsize else None,
            "input_count": len(tx.inputs),
            "output_count": len(tx.outputs),
            "vsize": tx.vsize,
            "value_imbalance": (total_in - total_out) / total_in if total_in else None,
            "output_value_cv": _cv(outs),
            "max_equal_outputs": max(eq.values()) if eq else 0,
            "repeated_output_values": sum(c for c in eq.values() if c > 1),
            "round_output_ratio": sum(1 for v in outs if v % ROUND_UNIT == 0) / len(outs) if outs else None,
            "fan_in": len(uniq_in),
            "fan_out": len(uniq_out),
            "secs_since_prev_related": (t - max(prev_times)).total_seconds() if prev_times else None,
            "min_input_holding_secs": min(holding) if holding else None,
            "chain_depth": depth,
            "unique_counterparties": len(uniq_in | uniq_out),
            "output_address_reuse_ratio": sum(1 for a in uniq_out if a in addr) / len(uniq_out) if uniq_out else None,
            "fresh_input_ratio": fresh / len(uniq_in) if uniq_in else None,
            "graph_degree": len(uniq_in) + len(uniq_out),
            "network_observation_count": len(early_obs) if tx.obs else None,
            "ip_diversity": len({o.src_ip for o in early_obs}) if tx.obs else None,
            "asn_diversity": len({o.asn for o in early_obs if o.asn is not None}) if any(o.asn for o in early_obs) else None,
            "src_ip_tx_10m": prior_10m + 1 if src_ns is not None else None,
            "src_ip_burst_score": round(burst, 4) if src_ns is not None else None,
            "src_ip_unique_addresses": len(src_ns.addresses) + len(uniq_in - set(src_ns.addresses)) if src_ns else None,
            "is_coinjoin_like": 1 if coinjoin_like(tx) else 0,
            "_as_of": (t + OBS_WINDOW).isoformat(),
        }
        tx_out[tx.txid] = f

        # ---- update state AFTER computing features (no leakage)
        for side, items in (("in", tx.inputs), ("out", tx.outputs)):
            for a, v, _ in items:
                st = addr.get(a)
                if st is None:
                    st = addr[a] = AddrState(first_seen=t, last_seen=t)
                if st.tx_count and st.txids[-1] != tx.txid:
                    st.intervals_sum += (t - st.last_seen).total_seconds()
                if not st.txids or st.txids[-1] != tx.txid:
                    st.tx_count += 1
                    st.txids.append(tx.txid)
                st.last_seen = t
                st.max_value = max(st.max_value, v)
                if side == "in":
                    st.out_count += 1
                    st.spent += v
                    st.out_neighbours |= uniq_out - {a}
                else:
                    st.in_count += 1
                    st.received += v
                    st.last_received = t
                    st.depth = max(st.depth, depth)
                    st.in_neighbours |= uniq_in - {a}
                st.counterparties |= (uniq_in | uniq_out) - {a}
                if first:
                    st.ips.add(first.src_ip)
                    if first.asn is not None:
                        st.asns.add(first.asn)
        for o in tx.obs:
            for key, store in ((o.src_ip, ips), (str(o.asn) if o.asn is not None else None, asns), (o.country, countries)):
                if key is None:
                    continue
                ns = store[key]
                if tx.txid not in ns.txids:
                    ns.txids.add(tx.txid)
                    ns.value += total_out
                    ns.all_times.append(t)
                    ns.times.append(t)
                    while ns.times and t - ns.times[0] > BURST_WINDOW:
                        ns.times.popleft()
                    ns.max_burst = max(ns.max_burst, len(ns.times))
                    for a in uniq_in:
                        ns.addresses[a] += 1
                ns.ports.update({o.src_port, o.dst_port})
                if o.asn is not None:
                    ns.asns.add(o.asn)
                if o.country:
                    ns.countries.add(o.country)
                ns.ips.add(o.src_ip)

    addresses: dict[str, dict[str, Any]] = {}
    for a, st in addr.items():
        active_days = max((st.last_seen - st.first_seen).total_seconds() / 86400, 1 / 24)
        addresses[a] = {
            "first_seen": st.first_seen.isoformat(),
            "last_seen": st.last_seen.isoformat(),
            "tx_count": st.tx_count,
            "incoming_tx_count": st.in_count,
            "outgoing_tx_count": st.out_count,
            "total_received_sat": st.received,
            "total_spent_sat": st.spent,
            "avg_tx_value_sat": (st.received + st.spent) // max(st.in_count + st.out_count, 1),
            "max_tx_value_sat": st.max_value,
            "unique_counterparties": len(st.counterparties),
            "tx_per_day": st.tx_count / active_days,
            "avg_interval_secs": st.intervals_sum / (st.tx_count - 1) if st.tx_count > 1 else None,
            "graph_in_degree": len(st.in_neighbours),
            "graph_out_degree": len(st.out_neighbours),
            "network_association_count": len(st.ips),
            "ip_diversity": len(st.ips),
            "asn_diversity": len(st.asns),
            "max_chain_depth": st.depth,
            # filled by the graph stage:
            "component_size": None,
            "betweenness": None,
            "cluster_ids": [],
        }
    network: dict[tuple[str, str], dict[str, Any]] = {}
    for etype, store in (("ip", ips), ("asn", asns), ("country", countries)):
        for k, ns in store.items():
            span = max((max(ns.all_times) - min(ns.all_times)).total_seconds() / 86400, 1 / 24) if ns.all_times else None
            network[(etype, k)] = {
                "unique_tx_count": len(ns.txids),
                "unique_address_count": len(ns.addresses),
                "total_observed_value_sat": ns.value,
                "tx_per_day": len(ns.txids) / span if span else None,
                "max_tx_in_10m": ns.max_burst,
                "port_diversity": len(ns.ports),
                "asn_diversity": len(ns.asns),
                "country_diversity": len(ns.countries),
                "ip_diversity": len(ns.ips),
                "repeated_wallet_associations": sum(1 for c in ns.addresses.values() if c >= 2),
                "first_seen": min(ns.all_times).isoformat() if ns.all_times else None,
                "last_seen": max(ns.all_times).isoformat() if ns.all_times else None,
            }
    return FeatureResult(tx_out, addresses, network, last_t)


def model_vector(f: dict[str, Any]) -> list[float]:
    """Numeric vector for TX_FEATURES; NaN marks missing (imputed + indicator-flagged downstream)."""
    out: list[float] = []
    for k in TX_FEATURES:
        v = f.get(k)
        if v is None:
            out.append(math.nan)
        elif k in LOG_FEATURES:
            out.append(math.log1p(max(float(v), 0.0)))
        else:
            out.append(float(v))
    return out
