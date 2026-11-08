"""Record validation and normalisation into canonical form.

Rules:
- Any `error` issue quarantines the record. Only `warning` issues -> `partial`. None -> `valid`.
- Monetary values are integer satoshis. Integers are read as satoshis; decimal strings (e.g. "0.5")
  are read as BTC and converted exactly with Decimal. Sub-satoshi precision is an error.
  Floats are never used for arithmetic.
- Timestamps are normalised to UTC. Naive timestamps are assumed UTC and flagged as a warning.
"""

import ipaddress
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.hashing import content_hash
from app.ingestion.address_codec import classify_address
from app.models.base import DataQuality

SAT_PER_BTC = 100_000_000
MAX_SUPPLY_SAT = 21_000_000 * SAT_PER_BTC
TXID_RE = re.compile(r"^[0-9a-fA-F]{64}$")
KNOWN_SCRIPT_TYPES = {"p2pkh", "p2sh", "p2wpkh", "p2wsh", "p2tr", "p2sh-p2wpkh", "multisig", "nulldata", "mixed"}
REQUIRED = (
    "timestamp",
    "src_ip",
    "dst_ip",
    "src_port",
    "dst_port",
    "txid",
    "input_addresses",
    "output_addresses",
    "input_amounts",
    "output_amounts",
    "fee",
    "script_type",
)
OPTIONAL_INT = ("block_height", "confirmations", "version", "locktime", "size", "vsize", "weight", "asn")


@dataclass
class Issue:
    field: str | None
    code: str
    message: str
    severity: str  # "error" | "warning"


@dataclass
class NormalisedRecord:
    data: dict[str, Any] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)

    @property
    def quality(self) -> DataQuality:
        if any(i.severity == "error" for i in self.issues):
            return DataQuality.quarantined
        if self.issues:
            return DataQuality.partial
        return DataQuality.valid

    def err(self, f: str | None, code: str, msg: str) -> None:
        self.issues.append(Issue(f, code, msg, "error"))

    def warn(self, f: str | None, code: str, msg: str) -> None:
        self.issues.append(Issue(f, code, msg, "warning"))

    @property
    def tx_hash(self) -> str:
        """Hash of blockchain-layer content only; same txid must always have the same content."""
        keys = ("txid", "input_addresses", "output_addresses", "input_amounts", "output_amounts", "fee")
        return content_hash({k: self.data.get(k) for k in keys})

    @property
    def obs_hash(self) -> str:
        keys = ("timestamp", "src_ip", "dst_ip", "src_port", "dst_port", "txid", "protocol")
        return content_hash({k: self.data.get(k) for k in keys})

    @property
    def record_hash(self) -> str:
        return content_hash(self.data)


def to_satoshis(value: Any) -> int:
    """Convert to integer satoshis. Raises ValueError for invalid / negative / sub-satoshi values."""
    if isinstance(value, bool) or value is None:
        raise ValueError("amount missing or not numeric")
    if isinstance(value, int):
        sat = value
    else:
        text = str(value).strip().upper().removesuffix("BTC").strip()
        if text.endswith("SAT"):
            text = text.removesuffix("SAT").strip()
            if not re.fullmatch(r"-?\d+", text):
                raise ValueError(f"invalid satoshi amount {value!r}")
            sat = int(text)
        else:
            try:
                d = Decimal(text)
            except InvalidOperation as e:
                raise ValueError(f"invalid amount {value!r}") from e
            if not d.is_finite():
                raise ValueError(f"invalid amount {value!r}")
            if "." in text or "E" in text:
                scaled = d * SAT_PER_BTC
                if scaled != scaled.to_integral_value():
                    raise ValueError(f"amount {value!r} has sub-satoshi precision")
                sat = int(scaled)
            else:
                sat = int(d)
    if sat < 0:
        raise ValueError("amount is negative")
    if sat > MAX_SUPPLY_SAT:
        raise ValueError("amount exceeds 21M BTC supply")
    return sat


def parse_timestamp(value: Any) -> tuple[datetime, bool]:
    """Returns (utc_datetime, was_naive)."""
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if re.fullmatch(r"\d{9,11}", text):  # unix epoch seconds
            return datetime.fromtimestamp(int(text), tz=UTC), False
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC), True
    return dt.astimezone(UTC), False


def _ip(rec: NormalisedRecord, raw: dict[str, Any], key: str) -> None:
    try:
        rec.data[key] = str(ipaddress.ip_address(str(raw[key]).strip()))
    except (ValueError, TypeError):
        rec.err(key, "invalid_ip", f"{key} is not a valid IPv4/IPv6 address")


def _port(rec: NormalisedRecord, raw: dict[str, Any], key: str) -> None:
    try:
        p = int(str(raw[key]).strip())
        if not 0 <= p <= 65535:
            raise ValueError
        rec.data[key] = p
    except (ValueError, TypeError):
        rec.err(key, "invalid_port", f"{key} must be an integer in 0..65535")


def _as_list(v: Any) -> list[Any] | None:
    if isinstance(v, list):
        return v
    if v is None:
        return None
    if isinstance(v, str):
        from app.ingestion.parsers import _split_array

        r = _split_array(v)
        return r if isinstance(r, list) else None
    return None


def normalise(raw: dict[str, Any]) -> NormalisedRecord:
    rec = NormalisedRecord()
    raw = {str(k).strip().lower(): v for k, v in raw.items()}
    for k in REQUIRED:
        if k not in raw or raw[k] is None or raw[k] == "":
            if k == "script_type":
                continue
            rec.err(k, "missing_field", f"required field {k} is missing")
    if any(i.code == "missing_field" and i.field in ("txid", "timestamp") for i in rec.issues):
        return rec

    try:
        ts, naive = parse_timestamp(raw["timestamp"])
        rec.data["timestamp"] = ts.isoformat()
        if naive:
            rec.warn("timestamp", "naive_timestamp", "timestamp had no timezone; assumed UTC")
    except (ValueError, TypeError, OverflowError):
        rec.err("timestamp", "invalid_timestamp", "timestamp is not ISO-8601 or epoch seconds")

    txid = str(raw["txid"]).strip()
    if TXID_RE.fullmatch(txid):
        rec.data["txid"] = txid.lower()
    else:
        rec.err("txid", "invalid_txid", "txid must be 64 hexadecimal characters")

    for key in ("src_ip", "dst_ip"):
        if key in raw and raw[key] is not None:
            _ip(rec, raw, key)
    for key in ("src_port", "dst_port"):
        if key in raw and raw[key] is not None:
            _port(rec, raw, key)

    for side in ("input", "output"):
        addrs = _as_list(raw.get(f"{side}_addresses"))
        amts = _as_list(raw.get(f"{side}_amounts"))
        if addrs is None or amts is None:
            if not any(i.field in (f"{side}_addresses", f"{side}_amounts") for i in rec.issues):
                rec.err(f"{side}_addresses", "invalid_array", f"{side} addresses/amounts must be arrays")
            continue
        if len(addrs) == 0:
            rec.err(f"{side}_addresses", "empty_array", f"transaction has no {side}s")
        if len(addrs) != len(amts):
            rec.err(f"{side}_amounts", "length_mismatch", f"{side}_addresses and {side}_amounts lengths differ")
            continue
        clean_addrs: list[str] = []
        types: list[str] = []
        for i, a in enumerate(addrs):
            a = str(a).strip()
            info = classify_address(a)
            if info is None:
                rec.err(f"{side}_addresses", "invalid_address", f"{side} address #{i} fails checksum/format validation")
            else:
                types.append(info.address_type)
            clean_addrs.append(a)
        sats: list[int] = []
        converted = False
        for i, v in enumerate(amts):
            try:
                sats.append(to_satoshis(v))
                converted |= not isinstance(v, int) and "." in str(v)
            except ValueError as e:
                rec.err(f"{side}_amounts", "invalid_amount", f"{side} amount #{i}: {e}")
        rec.data[f"{side}_addresses"] = clean_addrs
        rec.data[f"{side}_amounts"] = sats
        rec.data[f"{side}_address_types"] = types
        if converted:
            rec.warn(f"{side}_amounts", "btc_converted", f"{side} amounts given in BTC were converted to satoshis")

    try:
        rec.data["fee"] = to_satoshis(raw.get("fee"))
    except ValueError as e:
        rec.err("fee", "invalid_fee", f"fee: {e}")

    ins, outs = rec.data.get("input_amounts"), rec.data.get("output_amounts")
    if (
        isinstance(ins, list)
        and isinstance(outs, list)
        and "fee" in rec.data
        and len(ins) == len(rec.data.get("input_addresses", []))
        and len(outs) == len(rec.data.get("output_addresses", []))
    ):
        diff = sum(ins) - sum(outs)
        if diff < 0:
            rec.err("output_amounts", "outputs_exceed_inputs", "sum(outputs) exceeds sum(inputs)")
        elif diff != rec.data["fee"]:
            rec.err("fee", "fee_mismatch", f"fee {rec.data['fee']} != sum(inputs)-sum(outputs) {diff}")

    st = raw.get("script_type")
    if st is None:
        rec.data["script_type"] = None
        rec.warn("script_type", "missing_script_type", "script_type not provided")
    else:
        s = str(st).strip().lower()
        rec.data["script_type"] = s
        if s not in KNOWN_SCRIPT_TYPES:
            rec.warn("script_type", "unknown_script_type", f"script_type {s!r} not recognised")

    geo = raw.get("geo_country")
    if geo is None or str(geo).strip() == "":
        rec.data["geo_country"] = None
    elif re.fullmatch(r"[A-Za-z]{2}", str(geo).strip()):
        rec.data["geo_country"] = str(geo).strip().upper()
    else:
        rec.data["geo_country"] = None
        rec.warn("geo_country", "invalid_country", "geo_country is not an ISO-3166 alpha-2 code; dropped")

    for k in OPTIONAL_INT:
        v = raw.get(k)
        if v is None or str(v).strip() == "":
            rec.data[k] = None
            continue
        try:
            n = int(str(v).strip())
            if n < 0:
                raise ValueError
            rec.data[k] = n
        except ValueError:
            rec.data[k] = None
            rec.warn(k, "invalid_optional_int", f"{k} is not a non-negative integer; dropped")

    bh = raw.get("block_hash")
    if bh and TXID_RE.fullmatch(str(bh).strip()):
        rec.data["block_hash"] = str(bh).strip().lower()
    else:
        rec.data["block_hash"] = None
        if bh:
            rec.warn("block_hash", "invalid_block_hash", "block_hash is not 64 hex chars; dropped")
    rec.data["protocol"] = (str(raw["protocol"]).strip().lower() or None) if raw.get("protocol") else None
    known = set(REQUIRED) | set(OPTIONAL_INT) | {"geo_country", "block_hash", "protocol", "raw_tx"}
    rec.data["extra"] = {k: v for k, v in raw.items() if k not in known}
    return rec
