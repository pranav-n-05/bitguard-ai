from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.ingestion.normalize import normalise, parse_timestamp, to_satoshis
from app.models.base import DataQuality

A1 = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"
A2 = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"


def base(**kw: object) -> dict[str, object]:
    r: dict[str, object] = {
        "timestamp": "2026-01-02T03:04:05Z",
        "src_ip": "198.51.100.7",
        "dst_ip": "2001:db8::1",
        "src_port": 50000,
        "dst_port": 8333,
        "txid": "ab" * 32,
        "input_addresses": [A1],
        "output_addresses": [A2, A1],
        "input_amounts": [100_000],
        "output_amounts": [60_000, 39_000],
        "fee": 1000,
        "script_type": "p2wpkh",
        "geo_country": "in",
        "asn": 9829,
    }
    r.update(kw)
    return r


@pytest.mark.parametrize(
    ("value", "sat"),
    [
        (5, 5),
        ("5", 5),
        ("0.5", 50_000_000),
        ("1.00000001", 100_000_001),
        ("0.1 BTC", 10_000_000),
        ("12 sat", 12),
        (Decimal("0.00000001"), 1),
        ("21000000.0", 2_100_000_000_000_000),
    ],
)
def test_to_satoshis(value: object, sat: int) -> None:
    assert to_satoshis(value) == sat
    assert isinstance(to_satoshis(value), int)


@pytest.mark.parametrize("bad", ["0.000000001", "-1", "abc", None, True, "NaN", "21000000.00000001", "1e-9"])
def test_to_satoshis_rejects(bad: object) -> None:
    with pytest.raises(ValueError):
        to_satoshis(bad)


def test_float_precision_not_used() -> None:
    # 0.1 + 0.2 as BTC strings must be exact in satoshis
    assert to_satoshis("0.1") + to_satoshis("0.2") == to_satoshis("0.3")


@pytest.mark.parametrize(
    ("raw", "expected", "naive"),
    [
        ("2026-01-02T08:34:05+05:30", datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), False),
        ("2026-01-02T03:04:05Z", datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), False),
        ("2026-01-02T03:04:05", datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), True),
        ("1767323045", datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), False),
    ],
)
def test_timestamp_normalised_to_utc(raw: str, expected: datetime, naive: bool) -> None:
    dt, was_naive = parse_timestamp(raw)
    assert dt == expected and dt.tzinfo == UTC and was_naive is naive


def test_valid_record() -> None:
    n = normalise(base())
    assert n.quality == DataQuality.valid, n.issues
    assert n.data["geo_country"] == "IN"
    assert n.data["output_amounts"] == [60_000, 39_000]


def test_naive_timestamp_is_partial() -> None:
    n = normalise(base(timestamp="2026-01-02T03:04:05"))
    assert n.quality == DataQuality.partial
    assert [i.code for i in n.issues] == ["naive_timestamp"]


@pytest.mark.parametrize(
    ("override", "code"),
    [
        ({"txid": "xyz"}, "invalid_txid"),
        ({"src_ip": "300.1.1.1"}, "invalid_ip"),
        ({"dst_port": 70000}, "invalid_port"),
        ({"fee": 999}, "fee_mismatch"),
        ({"output_amounts": [60_000]}, "length_mismatch"),
        ({"output_amounts": [90_000, 20_000]}, "outputs_exceed_inputs"),
        ({"input_addresses": [A1[:-1] + "5"]}, "invalid_address"),
        ({"timestamp": "yesterday"}, "invalid_timestamp"),
        ({"input_amounts": ["0.000000001"]}, "invalid_amount"),
    ],
)
def test_quarantine_reasons(override: dict[str, object], code: str) -> None:
    n = normalise(base(**override))
    assert n.quality == DataQuality.quarantined
    assert code in {i.code for i in n.issues}


def test_missing_required_field() -> None:
    r = base()
    del r["src_ip"]
    n = normalise(r)
    assert n.quality == DataQuality.quarantined
    assert ("src_ip", "missing_field") in {(i.field, i.code) for i in n.issues}


def test_null_geo_and_asn_are_unavailable_not_errors() -> None:
    n = normalise(base(geo_country=None, asn=None))
    assert n.quality == DataQuality.valid
    assert n.data["geo_country"] is None and n.data["asn"] is None


def test_btc_decimal_amounts_converted_with_warning() -> None:
    n = normalise(base(input_amounts=["0.001"], output_amounts=["0.0006", "0.00039"], fee="0.00001"))
    assert n.data["input_amounts"] == [100_000]
    assert n.quality == DataQuality.partial
    assert "btc_converted" in {i.code for i in n.issues}


def test_hashes_are_deterministic_and_format_independent() -> None:
    a = normalise(base())
    b = normalise(
        {**base(), "src_port": "50000", "fee": "1000", "input_amounts": ["100000"], "output_amounts": ["60000", "39000"]}
    )
    assert a.record_hash == b.record_hash and a.tx_hash == b.tx_hash
