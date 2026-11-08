"""Bitcoin address validation/encoding: Base58Check (P2PKH/P2SH) and Bech32/Bech32m (BIP-173/350).

Validation checks checksums and structure only; it says nothing about who controls an address.
"""

import hashlib
from dataclasses import dataclass

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58_IDX = {c: i for i, c in enumerate(_B58)}
_BECH32 = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_BECH32_CONST = 1
_BECH32M_CONST = 0x2BC830A3

_B58_VERSIONS = {0x00: ("p2pkh", "mainnet"), 0x05: ("p2sh", "mainnet"), 0x6F: ("p2pkh", "testnet"), 0xC4: ("p2sh", "testnet")}
_HRPS = {"bc": "mainnet", "tb": "testnet", "bcrt": "regtest"}


@dataclass(frozen=True)
class AddressInfo:
    address_type: str
    network: str


def _dsha(b: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(b).digest()).digest()


def b58encode_check(payload: bytes) -> str:
    data = payload + _dsha(payload)[:4]
    n = int.from_bytes(data, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = _B58[r] + out
    pad = len(data) - len(data.lstrip(b"\0"))
    return "1" * pad + out


def b58decode_check(s: str) -> bytes | None:
    n = 0
    for c in s:
        if c not in _B58_IDX:
            return None
        n = n * 58 + _B58_IDX[c]
    body = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    data = b"\0" * (len(s) - len(s.lstrip("1"))) + body
    if len(data) < 5:
        return None
    payload, chk = data[:-4], data[-4:]
    return payload if _dsha(payload)[:4] == chk else None


def _polymod(values: list[int]) -> int:
    gen = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
    chk = 1
    for v in values:
        top = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ v
        for i in range(5):
            chk ^= gen[i] if ((top >> i) & 1) else 0
    return chk


def _hrp_expand(hrp: str) -> list[int]:
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]


def _convertbits(data: bytes | list[int], frm: int, to: int, pad: bool) -> list[int] | None:
    acc = bits = 0
    ret: list[int] = []
    maxv = (1 << to) - 1
    for v in data:
        if v < 0 or v >> frm:
            return None
        acc = (acc << frm) | v
        bits += frm
        while bits >= to:
            bits -= to
            ret.append((acc >> bits) & maxv)
    if pad and bits:
        ret.append((acc << (to - bits)) & maxv)
    elif not pad and (bits >= frm or ((acc << (to - bits)) & maxv)):
        return None
    return ret


def segwit_encode(hrp: str, witver: int, program: bytes) -> str:
    const = _BECH32_CONST if witver == 0 else _BECH32M_CONST
    conv = _convertbits(program, 8, 5, True)
    assert conv is not None
    data = [witver, *conv]
    poly = _polymod(_hrp_expand(hrp) + data + [0] * 6) ^ const
    checksum = [(poly >> 5 * (5 - i)) & 31 for i in range(6)]
    return hrp + "1" + "".join(_BECH32[d] for d in data + checksum)


def segwit_decode(addr: str) -> tuple[str, int, bytes] | None:
    if addr.lower() != addr and addr.upper() != addr:
        return None
    addr = addr.lower()
    pos = addr.rfind("1")
    if pos < 1 or pos + 7 > len(addr) or len(addr) > 90:
        return None
    hrp, rest = addr[:pos], addr[pos + 1 :]
    if any(c not in _BECH32 for c in rest):
        return None
    data = [_BECH32.index(c) for c in rest]
    const = _polymod(_hrp_expand(hrp) + data)
    if const not in (_BECH32_CONST, _BECH32M_CONST):
        return None
    witver = data[0]
    prog = _convertbits(data[1:-6], 5, 8, False)
    if prog is None or not 2 <= len(prog) <= 40 or witver > 16:
        return None
    if (witver == 0 and const != _BECH32_CONST) or (witver != 0 and const != _BECH32M_CONST):
        return None
    if witver == 0 and len(prog) not in (20, 32):
        return None
    return hrp, witver, bytes(prog)


def classify_address(addr: str) -> AddressInfo | None:
    """Return type/network if the address is structurally valid with a correct checksum, else None."""
    if not addr or len(addr) > 90:
        return None
    lower = addr.lower()
    for hrp, net in _HRPS.items():
        if lower.startswith(hrp + "1"):
            dec = segwit_decode(addr)
            if dec is None or dec[0] != hrp:
                return None
            _, ver, prog = dec
            if ver == 0:
                return AddressInfo("p2wpkh" if len(prog) == 20 else "p2wsh", net)
            if ver == 1 and len(prog) == 32:
                return AddressInfo("p2tr", net)
            return AddressInfo(f"witness_v{ver}", net)
    payload = b58decode_check(addr)
    if payload is None or len(payload) != 21 or payload[0] not in _B58_VERSIONS:
        return None
    t, net = _B58_VERSIONS[payload[0]]
    return AddressInfo(t, net)
