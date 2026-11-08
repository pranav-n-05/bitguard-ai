"""Deterministic SYNTHETIC dataset generator.

Everything produced here is synthetic and labelled as such. It is modelled on real Bitcoin field
shapes (valid-checksum addresses, satoshi amounts, exact fee balance) but does not represent any
real transaction, address, person or IP owner.

Output: one row per network observation (a transaction may be observed several times), plus a
separate labels file describing injected patterns. Labels are for evaluation only and must never
be used as training features.
"""

import csv
import hashlib
import json
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from app.ingestion.address_codec import b58encode_check, segwit_encode

RELAY_PORT = 8333
SUSPICIOUS = ("fan_out_split", "consolidation_fan_in", "peel_chain", "cycle", "layering", "ip_burst")
BENIGN_CONTROLS = ("coinjoin_like", "large_normal")


@dataclass
class Actor:
    addresses: list[str]
    ips: list[str]
    asn: int
    country: str


@dataclass
class Generator:
    seed: int = 42
    n_actors: int = 300
    n_baseline_tx: int = 6000
    days: int = 60
    start: datetime = datetime(2026, 1, 1, tzinfo=UTC)
    error_rate: float = 0.01
    rows: list[dict[str, Any]] = field(default_factory=list)
    labels: dict[str, Any] = field(default_factory=lambda: {"txids": {}, "addresses": {}, "patterns": []})

    def __post_init__(self) -> None:
        self.rng = random.Random(self.seed)
        self._addr_counter = 0
        self.relays = [f"203.0.113.{i}" for i in range(1, 21)] + [f"2001:db8::{i:x}" for i in range(1, 6)]
        countries = ["IN", "IN", "IN", "US", "DE", "SG", "GB", "NL", "JP", "AE"]
        asns = [9829, 24560, 55836, 7018, 3320, 4657, 2856, 1136, 2516, 5384]
        self.actors: list[Actor] = []
        for i in range(self.n_actors):
            k = self.rng.randrange(len(countries))
            ips = [self._ip() for _ in range(self.rng.choice([1, 1, 2]))]
            self.actors.append(Actor([self.new_address() for _ in range(self.rng.randint(1, 3))], ips, asns[k], countries[k]))
            _ = i

    # ---------- primitives ----------
    def _ip(self) -> str:
        # Documentation / private-use ranges only (RFC 5737, RFC 1918) - never real hosts.
        block = self.rng.choice(["198.51.100", "192.0.2", "10.20", "172.16"])
        if block.count(".") == 1:
            return f"{block}.{self.rng.randint(0, 255)}.{self.rng.randint(1, 254)}"
        return f"{block}.{self.rng.randint(1, 254)}"

    def new_address(self) -> str:
        self._addr_counter += 1
        h = hashlib.sha256(f"bitguard-synthetic-{self.seed}-{self._addr_counter}".encode()).digest()
        kind = self.rng.random()
        if kind < 0.25:
            return b58encode_check(b"\x00" + h[:20])
        if kind < 0.35:
            return b58encode_check(b"\x05" + h[:20])
        if kind < 0.85:
            return segwit_encode("bc", 0, h[:20])
        return segwit_encode("bc", 1, h[:32])

    def _txid(self) -> str:
        return hashlib.sha256(f"tx-{self.seed}-{len(self.rows)}-{self.rng.random()}".encode()).hexdigest()

    def _time(self) -> datetime:
        return self.start + timedelta(seconds=self.rng.randint(0, self.days * 86400))

    @staticmethod
    def _script(addr: str) -> str:
        if addr.startswith("bc1p"):
            return "p2tr"
        if addr.startswith("bc1q"):
            return "p2wpkh"
        return "p2sh" if addr.startswith("3") else "p2pkh"

    def emit(
        self,
        ts: datetime,
        ins: list[tuple[str, int]],
        outs: list[tuple[str, int]],
        actor: Actor,
        *,
        src_ip: str | None = None,
        observations: int | None = None,
        label: str | None = None,
    ) -> str:
        fee = sum(a for _, a in ins) - sum(a for _, a in outs)
        assert fee >= 0, "synthetic generator produced negative fee"
        txid = self._txid()
        scripts = {self._script(a) for a, _ in ins}
        script_type = scripts.pop() if len(scripts) == 1 else "mixed"
        height = 930_000 + int((ts - self.start).total_seconds() // 600)
        base = {
            "txid": txid,
            "input_addresses": [a for a, _ in ins],
            "output_addresses": [a for a, _ in outs],
            "input_amounts": [v for _, v in ins],
            "output_amounts": [v for _, v in outs],
            "fee": fee,
            "script_type": script_type,
            "block_height": height,
            "block_hash": hashlib.sha256(f"block-{height}".encode()).hexdigest(),
            "vsize": 110 + 68 * len(ins) + 31 * len(outs),
            "version": 2,
            "locktime": 0,
        }
        n_obs = observations if observations is not None else self.rng.choice([1, 1, 2, 3])
        first_ip = src_ip or self.rng.choice(actor.ips)
        for j in range(n_obs):
            seen = ts + timedelta(milliseconds=self.rng.randint(0, 4000) * j)
            ip = first_ip if j == 0 else self.rng.choice(self.relays)
            self.rows.append(
                {
                    "timestamp": seen.isoformat().replace("+00:00", "Z"),
                    "src_ip": ip,
                    "dst_ip": self.rng.choice(self.relays),
                    "src_port": self.rng.randint(40000, 65000) if j == 0 else RELAY_PORT,
                    "dst_port": RELAY_PORT,
                    "protocol": "bitcoin-p2p",
                    "geo_country": actor.country if j == 0 else self.rng.choice(["NL", "DE", "US", None]),
                    "asn": actor.asn if j == 0 else self.rng.choice([1136, 3320, 7018]),
                    **base,
                }
            )
        if label:
            self.labels["txids"][txid] = label
        return txid

    def _amount(self, lo: int = 50_000, hi: int = 20_000_000) -> int:
        return int(self.rng.lognormvariate(13.5, 1.2)) % (hi - lo) + lo

    def _record(self, pattern: str, txids: list[str], addresses: list[str], desc: str, benign: bool = False) -> None:
        self.labels["patterns"].append(
            {"pattern": pattern, "suspicious": not benign, "txids": txids, "addresses": addresses, "description": desc}
        )
        for a in addresses:
            self.labels["addresses"].setdefault(a, pattern)

    # ---------- baseline ----------
    def baseline(self) -> None:
        for _ in range(self.n_baseline_tx):
            sender = self.rng.choice(self.actors)
            receiver = self.rng.choice(self.actors)
            ts = self._time()
            n_in = self.rng.choice([1, 1, 1, 2, 2, 3])
            ins = [(self.rng.choice(sender.addresses), self._amount()) for _ in range(n_in)]
            total = sum(v for _, v in ins)
            fee = self.rng.randint(500, 6000)
            pay = self.rng.randint(total // 10, max(total // 10 + 1, total - fee - 1000))
            change_addr = self.new_address()
            sender.addresses.append(change_addr)
            outs = [(self.rng.choice(receiver.addresses), pay), (change_addr, total - fee - pay)]
            self.rng.shuffle(outs)
            self.emit(ts, ins, [o for o in outs if o[1] > 0], sender)

    # ---------- injected patterns ----------
    def fan_out(self) -> None:
        a = self.rng.choice(self.actors)
        src = self.new_address()
        n = self.rng.randint(25, 50)
        each = self.rng.randint(90_000, 110_000) * 10
        total = each * n + 20_000
        outs = [(self.new_address(), each + self.rng.randint(-50, 50)) for _ in range(n)]
        diff = total - sum(v for _, v in outs) - 8000
        txid = self.emit(self._time(), [(src, total)], [*outs, (self.new_address(), diff)], a, label="fan_out_split")
        self._record("fan_out_split", [txid], [src] + [o[0] for o in outs], f"One input split into {n} near-equal outputs")

    def fan_in(self) -> None:
        a = self.rng.choice(self.actors)
        n = self.rng.randint(20, 40)
        ins = [(self.new_address(), self.rng.randint(40_000, 400_000)) for _ in range(n)]
        dst = self.new_address()
        txid = self.emit(self._time(), ins, [(dst, sum(v for _, v in ins) - 15_000)], a, label="consolidation_fan_in")
        self._record("consolidation_fan_in", [txid], [x[0] for x in ins] + [dst], f"{n} inputs consolidated to one output")

    def peel_chain(self) -> None:
        a = self.rng.choice(self.actors)
        ts = self._time()
        cur, bal = self.new_address(), self.rng.randint(200_000_000, 900_000_000)
        txids, addrs = [], [cur]
        for _ in range(self.rng.randint(8, 15)):
            peel = self.rng.randint(1_000_000, 9_000_000)
            nxt, peel_to = self.new_address(), self.new_address()
            fee = 3000
            txids.append(self.emit(ts, [(cur, bal)], [(peel_to, peel), (nxt, bal - peel - fee)], a, label="peel_chain"))
            addrs += [nxt, peel_to]
            cur, bal = nxt, bal - peel - fee
            ts += timedelta(minutes=self.rng.randint(2, 25))
        self._record("peel_chain", txids, addrs, f"Peel chain of {len(txids)} hops with small peeled outputs")

    def cycle(self) -> None:
        a = self.rng.choice(self.actors)
        ring = [self.new_address() for _ in range(self.rng.randint(3, 5))]
        ts, amt, txids = self._time(), self.rng.randint(50_000_000, 150_000_000), []
        for i, src in enumerate(ring):
            dst = ring[(i + 1) % len(ring)]
            txids.append(self.emit(ts, [(src, amt)], [(dst, amt - 2500)], a, label="cycle"))
            amt -= 2500
            ts += timedelta(minutes=self.rng.randint(5, 60))
        self._record("cycle", txids, ring, f"Funds return to origin through a {len(ring)}-address cycle")

    def layering(self) -> None:
        a = self.rng.choice(self.actors)
        ts, amt = self._time(), self.rng.randint(300_000_000, 800_000_000)
        cur, txids, addrs = self.new_address(), [], []
        addrs.append(cur)
        for _ in range(self.rng.randint(5, 8)):
            parts = self.rng.randint(2, 3)
            outs = [(self.new_address(), (amt - 4000) // parts) for _ in range(parts)]
            outs[0] = (outs[0][0], amt - 4000 - sum(v for _, v in outs[1:]))
            txids.append(self.emit(ts, [(cur, amt)], outs, a, label="layering"))
            addrs += [o[0] for o in outs]
            cur, amt = outs[0]
            ts += timedelta(seconds=self.rng.randint(30, 240))
        self._record("layering", txids, addrs, "Rapid multi-hop transfers through fresh addresses")

    def ip_burst(self) -> None:
        a = self.rng.choice(self.actors)
        ip, ts, txids, addrs = self._ip(), self._time(), [], []
        for _ in range(self.rng.randint(25, 40)):
            src, dst = self.new_address(), self.new_address()
            v = self._amount()
            txids.append(self.emit(ts, [(src, v)], [(dst, v - 2000)], a, src_ip=ip, observations=1, label="ip_burst"))
            addrs += [src, dst]
            ts += timedelta(seconds=self.rng.randint(5, 25))
        self._record("ip_burst", txids, addrs, f"{len(txids)} transactions first-observed from {ip} within minutes")

    def coinjoin_like(self) -> None:
        participants = self.rng.sample(self.actors, self.rng.randint(5, 10))
        denom = self.rng.choice([10_000_000, 5_000_000, 1_000_000])
        ins, outs = [], []
        for p in participants:
            v = denom + self.rng.randint(50_000, 900_000)
            ins.append((self.rng.choice(p.addresses), v))
            outs.append((self.new_address(), denom))
            outs.append((self.new_address(), v - denom - 3000))
        self.rng.shuffle(outs)
        txid = self.emit(self._time(), ins, outs, participants[0], label="coinjoin_like")
        self._record(
            "coinjoin_like",
            [txid],
            [x[0] for x in ins],
            "CoinJoin-like equal-output structure (privacy, NOT malicious)",
            benign=True,
        )

    def large_normal(self) -> None:
        s, r = self.rng.sample(self.actors, 2)
        v = self.rng.randint(5_000_000_000, 30_000_000_000)
        change = self.new_address()
        txid = self.emit(
            self._time(),
            [(self.rng.choice(s.addresses), v)],
            [(self.rng.choice(r.addresses), v - 1_000_000 - 4000), (change, 1_000_000)],
            s,
            label="large_normal",
        )
        self._record("large_normal", [txid], [], "Large but structurally ordinary payment (benign control)", benign=True)

    def inject_errors(self) -> int:
        n = int(len(self.rows) * self.error_rate)
        corruptions = [
            lambda r: r.update(txid="zz" + r["txid"][2:]),
            lambda r: r.update(src_ip="999.1.1.1"),
            lambda r: r.update(fee=r["fee"] + 1),
            lambda r: r.update(output_amounts=r["output_amounts"][:-1]) if len(r["output_amounts"]) > 1 else r.update(fee=-5),
            lambda r: r.update(
                input_addresses=[r["input_addresses"][0][:-1] + ("A" if r["input_addresses"][0][-1] != "A" else "B")]
                + r["input_addresses"][1:]
            ),
            lambda r: r.update(timestamp="not-a-date"),
            lambda r: r.update(dst_port=70000),
        ]
        bad = []
        for _ in range(n):
            r = json.loads(json.dumps(self.rng.choice(self.rows)))
            corrupt: Any = self.rng.choice(corruptions)
            corrupt(r)
            r["_synthetic_corruption"] = True
            bad.append(r)
        dups = [dict(self.rng.choice(self.rows)) for _ in range(n)]  # exact duplicates
        self.rows.extend(bad + dups)
        self.labels["injected_errors"] = len(bad)
        self.labels["injected_duplicates"] = len(dups)
        return n

    def generate(self, patterns_per_type: int = 6) -> "Generator":
        self.baseline()
        for _ in range(patterns_per_type):
            self.fan_out()
            self.fan_in()
            self.peel_chain()
            self.cycle()
            self.layering()
            self.ip_burst()
            self.coinjoin_like()
            self.large_normal()
        if self.error_rate > 0:
            self.inject_errors()
        self.rows.sort(key=lambda r: r["timestamp"] if r["timestamp"] != "not-a-date" else "9")
        self.labels["meta"] = {
            "synthetic": True,
            "seed": self.seed,
            "rows": len(self.rows),
            "unique_txids": len({r["txid"] for r in self.rows}),
            "note": "Synthetic data. Labels are for evaluation only; never train on them.",
        }
        return self

    # ---------- writers ----------
    def write(self, out_dir: Path, fmt: str = "jsonl", name: str = "transactions") -> Path:
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{name}.{fmt}"
        rows = [{k: v for k, v in r.items() if not k.startswith("_")} for r in self.rows]
        if fmt == "jsonl":
            path.write_text("".join(json.dumps(r) + "\n" for r in rows))
        elif fmt == "json":
            path.write_text(json.dumps({"synthetic": True, "transactions": rows}))
        elif fmt == "csv":
            cols = list(dict.fromkeys(k for r in rows for k in r))
            with path.open("w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=cols)
                w.writeheader()
                for r in rows:
                    w.writerow({k: json.dumps(v) if isinstance(v, list) else ("" if v is None else v) for k, v in r.items()})
        elif fmt == "xml":
            with path.open("w") as f:
                f.write('<?xml version="1.0" encoding="UTF-8"?>\n<transactions synthetic="true">\n')
                for r in rows:
                    f.write("  <transaction>")
                    for k, v in r.items():
                        if isinstance(v, list):
                            item = "address" if "addresses" in k else "amount"
                            f.write(f"<{k}>" + "".join(f"<{item}>{escape(str(x))}</{item}>" for x in v) + f"</{k}>")
                        elif v is None:
                            f.write(f'<{k} nil="true"/>')
                        else:
                            f.write(f"<{k}>{escape(str(v))}</{k}>")
                    f.write("</transaction>\n")
                f.write("</transactions>\n")
        else:
            raise ValueError(fmt)
        (out_dir / f"{name}.labels.json").write_text(json.dumps(self.labels, indent=1))
        return path
