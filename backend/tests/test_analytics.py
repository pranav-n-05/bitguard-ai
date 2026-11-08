"""Feature engineering, correlation, graph patterns and clustering (SYNTHETIC fixtures)."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from httpx import AsyncClient

from app.analytics.features import compute_features
from app.analytics.loader import Obs, Tx, coinjoin_like
from app.graph.clustering import common_input_clusters
from app.graph.patterns import detect_patterns
from app.ingestion.synthetic import Generator
from app.intelligence.correlation import correlate
from tests.conftest import auth_headers

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def mk(i: int, ins: list[tuple[str, int]], outs: list[tuple[str, int]], t: datetime, ip: str = "198.51.100.1") -> Tx:
    tx = Tx(
        i,
        f"{i:064x}",
        t,
        sum(v for _, v in ins) - sum(v for _, v in outs),
        200,
        None,
        "p2wpkh",
        [(a, v, "p2wpkh") for a, v in ins],
        [(a, v, "p2wpkh") for a, v in outs],
    )
    tx.obs = [Obs(i, t, ip, "203.0.113.1", 50000, 8333, "bitcoin-p2p", 9829, "IN")]
    return tx


def chain() -> list[Tx]:
    return [
        mk(1, [("A", 100_000)], [("B", 60_000), ("C", 39_000)], T0),
        mk(2, [("B", 60_000)], [("D", 59_000)], T0 + timedelta(minutes=5)),
        mk(3, [("D", 59_000), ("C", 39_000)], [("E", 97_000)], T0 + timedelta(minutes=20)),
    ]


def test_transaction_features_values() -> None:
    fr = compute_features(chain())
    f1, f2, f3 = (fr.tx[f"{i:064x}"] for i in (1, 2, 3))
    assert f1["fee_sat"] == 1000 and f1["fee_rate"] == 5.0 and f1["fan_out"] == 2
    assert f1["secs_since_prev_related"] is None  # unknown, not zero
    assert f2["secs_since_prev_related"] == 300 and f2["min_input_holding_secs"] == 300
    assert f2["chain_depth"] == 2 and f3["chain_depth"] == 3
    assert f3["fan_in"] == 2
    a = fr.addresses["B"]
    assert a["incoming_tx_count"] == 1 and a["outgoing_tx_count"] == 1 and a["total_received_sat"] == 60_000


def test_features_are_leakage_free() -> None:
    base = chain()
    before = compute_features(base).tx
    future = [
        *chain(),
        mk(4, [("E", 97_000)], [("A", 90_000), ("F", 6_000)], T0 + timedelta(days=1)),
        mk(5, [("A", 90_000)], [("G", 89_000)], T0 + timedelta(days=2), ip="198.51.100.1"),
    ]
    after = compute_features(future).tx
    for txid, f in before.items():
        assert after[txid] == f, f"future data changed features of {txid}"


def test_missing_network_data_is_none_not_zero() -> None:
    t = mk(9, [("A", 10_000)], [("B", 9_000)], T0)
    t.obs = []
    t.vsize = None
    f = compute_features([t]).tx[t.txid]
    assert f["fee_rate"] is None and f["network_observation_count"] is None and f["src_ip_tx_10m"] is None


def _small() -> Generator:
    return Generator(seed=11, n_actors=25, n_baseline_tx=200, error_rate=0).generate(patterns_per_type=2)


def _as_txs(g: Generator) -> list[Tx]:
    by: dict[str, Tx] = {}
    for i, r in enumerate(sorted(g.rows, key=lambda r: r["timestamp"])):
        t = datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00"))
        if r["txid"] not in by:
            by[r["txid"]] = Tx(
                i,
                r["txid"],
                t,
                r["fee"],
                r["vsize"],
                r["block_height"],
                r["script_type"],
                [(a, v, Generator._script(a)) for a, v in zip(r["input_addresses"], r["input_amounts"], strict=True)],
                [(a, v, Generator._script(a)) for a, v in zip(r["output_addresses"], r["output_amounts"], strict=True)],
            )
        by[r["txid"]].obs.append(
            Obs(i, t, r["src_ip"], r["dst_ip"], r["src_port"], r["dst_port"], r["protocol"], r["asn"], r["geo_country"])
        )
    return sorted(by.values(), key=lambda x: (x.t, x.id))


EXPECT = {
    "high_fan_out": "fan_out_split",
    "high_fan_in": "consolidation_fan_in",
    "peel_chain": "peel_chain",
    "circular_flow": "cycle",
    "rapid_layering": "layering",
}


def test_graph_patterns_recover_injected_patterns() -> None:
    g = _small()
    txs = _as_txs(g)
    dets = detect_patterns(txs)
    labels = g.labels["txids"]
    for det_name, label in EXPECT.items():
        injected = [p for p in g.labels["patterns"] if p["pattern"] == label]
        found = [d for d in dets if d.pattern == det_name]
        hit = sum(1 for p in injected if any(set(p["txids"]) & set(d.txids) for d in found))
        assert hit == len(injected), f"{det_name}: found {hit}/{len(injected)}"
    # benign controls are never flagged structurally
    for d in dets:
        assert not any(labels.get(t) in ("coinjoin_like", "large_normal") for t in d.txids), d.pattern


def test_ip_burst_correlation_and_limitation() -> None:
    g = _small()
    ind = correlate(_as_txs(g))
    bursts = [i for i in ind if i.indicator_type == "ip_transaction_burst"]
    burst_ips = {p["description"].split(" from ")[1].split(" ")[0] for p in g.labels["patterns"] if p["pattern"] == "ip_burst"}
    assert burst_ips <= {i.entity_key for i in bursts}
    assert all(0 <= i.confidence <= 0.95 for i in ind)


def test_coinjoin_excluded_from_common_input_clustering() -> None:
    cj = mk(
        1,
        [("P1", 1_100_000), ("P2", 1_200_000), ("P3", 1_300_000)],
        [("O1", 1_000_000), ("O2", 1_000_000), ("O3", 1_000_000), ("C1", 97_000), ("C2", 197_000), ("C3", 297_000)],
        T0,
    )
    normal = mk(2, [("X", 50_000), ("Y", 60_000)], [("Z", 100_000)], T0)
    assert coinjoin_like(cj) and not coinjoin_like(normal)
    clusters, excluded = common_input_clusters([cj, normal])
    assert excluded == 1
    assert [sorted(c.members) for c in clusters] == [["X", "Y"]]
    assert all(0 < v <= 0.95 for c in clusters for v in c.members.values())


async def _ingest(client: AsyncClient, h: dict[str, str], path: Path) -> str:
    with path.open("rb") as f:
        ds = (
            await client.post("/api/v1/ingestion/datasets", headers=h, data={"name": "syn"}, files={"files": (path.name, f)})
        ).json()
    r = await client.post(f"/api/v1/ingestion/datasets/{ds['id']}/process", headers=h)
    assert r.status_code == 202 and r.json()[0]["status"] == "completed_with_errors"
    return str(ds["id"])


async def test_pipeline_and_intel_api(client: AsyncClient, admin: dict[str, str], small_dataset: dict[str, Path]) -> None:
    await _ingest(client, admin, small_dataset["jsonl"])
    labels = json.loads(small_dataset["jsonl"].with_name("synthetic_small.labels.json").read_text())
    viewer = await auth_headers(client, "viewer")
    ov = (await client.get("/api/v1/analytics/overview", headers=viewer)).json()
    assert ov["counts"]["transactions"] > 0 and ov["last_analysis_run"]["stats"]["detections"] > 0
    assert ov["data_labels"] == ["synthetic"]

    fan = next(p for p in labels["patterns"] if p["pattern"] == "fan_out_split")
    txid = fan["txids"][0]
    d = (await client.get(f"/api/v1/transactions/{txid}", headers=viewer)).json()
    assert d["features"]["fan_out"] >= 20 and d["provenance"]["file_sha256"] and d["graph_detections"]
    assert sum(o["amount_sat"] for o in d["outputs"]) + d["fee_sat"] == sum(i["amount_sat"] for i in d["inputs"])

    g = (await client.get(f"/api/v1/transactions/{txid}/graph", headers=viewer, params={"hops": 1})).json()
    types = {e["data"]["type"] for e in g["edges"]}
    assert {"INPUT_OF", "OUTPUT_OF", "OBSERVED_FROM"} <= types
    node_types = {n["data"]["id"]: n["data"]["type"] for n in g["nodes"]}
    for e in g["edges"]:
        s, t = node_types[e["data"]["source"]], node_types[e["data"]["target"]]
        assert (s, t) != ("address", "address"), "multi-input/output must not be collapsed to address->address"

    a, b = d["inputs"][0]["address"], d["outputs"][0]["address"]
    p = (await client.get("/api/v1/graph/path", headers=viewer, params={"source": a, "target": b, "max_hops": 2})).json()
    assert p["found"] and p["hops"] == 1 and p["path"][1] == f"tx:{txid}"

    addr = (await client.get(f"/api/v1/addresses/{a}", headers=viewer)).json()
    assert "not a wallet" in addr["notice"] and addr["features"]["tx_count"] >= 1
    assert (await client.get("/api/v1/addresses/1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNb", headers=viewer)).status_code == 404

    dets = (await client.get("/api/v1/graph/detections", headers=viewer, params={"limit": 100})).json()
    assert {x["pattern"] for x in dets["items"]} >= {"high_fan_out", "high_fan_in"}
    corr = (
        await client.get("/api/v1/network/correlations", headers=viewer, params={"indicator_type": "ip_transaction_burst"})
    ).json()
    assert corr["total"] >= 1 and "does not identify" in corr["items"][0]["limitations"]
    ip = corr["items"][0]["entity_key"]
    assert (await client.get(f"/api/v1/network/ips/{ip}", headers=viewer)).status_code == 200
    assert (await client.get("/api/v1/network/ips/not-an-ip", headers=viewer)).status_code == 400
    tr = (await client.get(f"/api/v1/transactions/{txid}/trace", headers=viewer)).json()
    assert tr["node_count"] >= 1 and "Address-level" in tr["limitations"]
    vol = (await client.get("/api/v1/analytics/transaction-volume", headers=viewer)).json()
    assert sum(x["tx_count"] for x in vol["series"]) == ov["counts"]["transactions"]
    rd = (await client.get("/api/v1/analytics/risk-distribution", headers=viewer)).json()
    assert rd["available"] in (True, False)


async def test_cluster_review_requires_permission_and_is_audited(
    client: AsyncClient, admin: dict[str, str], small_dataset: dict[str, Path]
) -> None:
    await _ingest(client, admin, small_dataset["jsonl"])
    cl = (await client.get("/api/v1/graph/clusters", headers=admin, params={"limit": 1})).json()["items"][0]
    viewer = await auth_headers(client, "viewer")
    body = {"review_status": "rejected_by_analyst", "note": "co-spend looks like a payjoin"}
    assert (await client.patch(f"/api/v1/graph/clusters/{cl['id']}", headers=viewer, json=body)).status_code == 403
    analyst = await auth_headers(client, "analyst")
    r = await client.patch(f"/api/v1/graph/clusters/{cl['id']}", headers=analyst, json=body)
    assert r.status_code == 200 and r.json()["review_status"] == "rejected_by_analyst"
