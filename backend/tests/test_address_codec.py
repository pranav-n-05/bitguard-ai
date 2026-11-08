import pytest

from app.ingestion.address_codec import b58encode_check, classify_address, segwit_decode, segwit_encode

VALID = [
    ("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", "p2pkh", "mainnet"),
    ("3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy", "p2sh", "mainnet"),
    ("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4", "p2wpkh", "mainnet"),  # BIP-173
    ("BC1QW508D6QEJXTDG4Y5R3ZARVARY0C5XW7KV8F3T4", "p2wpkh", "mainnet"),  # uppercase allowed
    ("bc1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3qccfmv3", "p2wsh", "mainnet"),
    ("bc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vqzk5jj0", "p2tr", "mainnet"),  # BIP-350
    ("tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx", "p2wpkh", "testnet"),
]
INVALID = [
    "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNb",  # bad base58 checksum
    "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t5",  # bad bech32 checksum
    "bc1pw508d6qejxtdg4y5r3zarvary0c5xw7kw508d6qejxtdg4y5r3zarvary0c5xw7kemeawh",  # v1 with bech32 (not m)
    "bc1QW508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4",  # mixed case
    "",
    "0OIl-not-base58",
]


@pytest.mark.parametrize(("addr", "kind", "net"), VALID)
def test_valid_addresses(addr: str, kind: str, net: str) -> None:
    info = classify_address(addr)
    assert info is not None and info.address_type == kind and info.network == net


@pytest.mark.parametrize("addr", INVALID)
def test_invalid_addresses(addr: str) -> None:
    assert classify_address(addr) is None


def test_roundtrip_encoders() -> None:
    prog = bytes(range(20))
    a = segwit_encode("bc", 0, prog)
    assert segwit_decode(a) == ("bc", 0, prog)
    assert classify_address(b58encode_check(b"\x00" + prog)) is not None
    assert classify_address(segwit_encode("bc", 1, bytes(32))).address_type == "p2tr"  # type: ignore[union-attr]
