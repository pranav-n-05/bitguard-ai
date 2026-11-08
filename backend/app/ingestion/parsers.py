"""Format/encoding detection and streaming parsers for CSV, JSON (array), JSON Lines and XML.

Each parser yields (record_index, raw_dict) or (record_index, ParseFailure). Parsing never
loads a whole file into memory except for encoding sniffing of the first chunk.
"""

import csv
import io
import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import ijson
from charset_normalizer import from_bytes
from lxml import etree

SUPPORTED_FORMATS = ("csv", "json", "jsonl", "xml")
ARRAY_FIELDS = ("input_addresses", "output_addresses", "input_amounts", "output_amounts")


@dataclass(frozen=True)
class ParseFailure:
    message: str
    raw: str | None = None


ParsedItem = tuple[int, dict[str, Any] | ParseFailure]


def detect_encoding(path: Path, sample_bytes: int = 64 * 1024) -> str:
    with path.open("rb") as f:
        head = f.read(sample_bytes)
    if head.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if not head:
        return "utf-8"
    try:
        head.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        best = from_bytes(head).best()
        return best.encoding if best else "utf-8"


def detect_format(path: Path, encoding: str) -> str:
    ext = path.suffix.lower().lstrip(".")
    if ext in ("ndjson",):
        return "jsonl"
    if ext in SUPPORTED_FORMATS:
        return ext
    with path.open("r", encoding=encoding, errors="replace") as f:
        head = f.read(4096).lstrip()
    if head.startswith("<"):
        return "xml"
    if head.startswith("["):
        return "json"
    if head.startswith("{"):
        first = head.splitlines()[0].strip()
        try:
            json.loads(first)
            return "jsonl"
        except json.JSONDecodeError:
            return "json"
    return "csv"


def _split_array(value: str) -> list[str] | str:
    v = value.strip()
    if v.startswith("["):
        try:
            parsed = json.loads(v)
            if isinstance(parsed, list):
                return [str(x) for x in parsed]
        except json.JSONDecodeError:
            return value
    if v == "":
        return []
    sep = "|" if "|" in v else ";"
    return [p.strip() for p in v.split(sep)]


def parse_csv(path: Path, encoding: str, start_after: int = -1) -> Iterator[ParsedItem]:
    with path.open("r", encoding=encoding, newline="") as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader):
            if idx <= start_after:
                continue
            if None in row:  # more cells than headers
                yield idx, ParseFailure("Row has more columns than header", raw=json.dumps(row.get(None)))
                continue
            rec: dict[str, Any] = {}
            for k, v in row.items():
                if k is None:
                    continue
                key = k.strip()
                if v is None:
                    rec[key] = None
                elif key in ARRAY_FIELDS:
                    rec[key] = _split_array(v)
                else:
                    rec[key] = v.strip() if v.strip() != "" else None
            yield idx, rec


def parse_jsonl(path: Path, encoding: str, start_after: int = -1) -> Iterator[ParsedItem]:
    with path.open("r", encoding=encoding) as f:
        idx = -1
        for line in f:
            if not line.strip():
                continue
            idx += 1
            if idx <= start_after:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                yield idx, ParseFailure(f"Invalid JSON line: {e.msg}", raw=line[:2000])
                continue
            yield idx, obj if isinstance(obj, dict) else ParseFailure("JSON line is not an object", raw=line[:2000])


def parse_json(path: Path, encoding: str, start_after: int = -1) -> Iterator[ParsedItem]:
    with path.open("rb") as raw:
        stream: Any = raw if encoding.startswith("utf-8") else io.TextIOWrapper(raw, encoding=encoding)
        head = raw.read(1024)
        raw.seek(0)
        prefix = "transactions.item" if head.lstrip().startswith(b"{") else "item"
        idx = -1
        try:
            for obj in ijson.items(stream, prefix, use_float=False):
                idx += 1
                if idx <= start_after:
                    continue
                yield idx, obj if isinstance(obj, dict) else ParseFailure("JSON array item is not an object")
        except ijson.JSONError as e:
            yield idx + 1, ParseFailure(f"Malformed JSON after record {idx}: {e}")


def _xml_value(el: Any) -> Any:
    children = list(el)
    if children:
        return [(c.text or "").strip() for c in children]
    text = (el.text or "").strip()
    if el.get("nil") == "true" or text == "":
        return None
    return text


def parse_xml(path: Path, encoding: str, start_after: int = -1) -> Iterator[ParsedItem]:
    # resolve_entities/no_network/huge_tree=False protect against XXE and billion-laughs.
    ctx = etree.iterparse(
        str(path),
        events=("end",),
        tag=("transaction", "record"),
        resolve_entities=False,
        no_network=True,
        huge_tree=False,
        load_dtd=False,
    )
    idx = -1
    try:
        for _, el in ctx:
            idx += 1
            if idx > start_after:
                rec = {child.tag: _xml_value(child) for child in el if isinstance(child.tag, str)}
                for k in ARRAY_FIELDS:
                    if isinstance(rec.get(k), str):
                        rec[k] = _split_array(rec[k])
                    elif rec.get(k) is None and k in rec:
                        rec[k] = []
                yield idx, rec
            el.clear()
            while el.getprevious() is not None:
                del el.getparent()[0]
    except etree.XMLSyntaxError as e:
        yield idx + 1, ParseFailure(f"Malformed XML after record {idx}: {e}")


_PARSERS = {"csv": parse_csv, "json": parse_json, "jsonl": parse_jsonl, "xml": parse_xml}


def iter_records(path: Path, fmt: str, encoding: str, start_after: int = -1) -> Iterator[ParsedItem]:
    if fmt not in _PARSERS:
        raise ValueError(f"Unsupported format {fmt!r}; supported: {SUPPORTED_FORMATS}")
    return _PARSERS[fmt](path, encoding, start_after)
