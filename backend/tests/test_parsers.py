from pathlib import Path

from app.ingestion.normalize import normalise
from app.ingestion.parsers import ParseFailure, detect_encoding, detect_format, iter_records


def _hashes(path: Path) -> list[str | None]:
    enc = detect_encoding(path)
    fmt = detect_format(path, enc)
    return [None if isinstance(r, ParseFailure) else normalise(r).record_hash for _, r in iter_records(path, fmt, enc)]


def test_all_formats_detected(small_dataset: dict[str, Path]) -> None:
    for fmt, p in small_dataset.items():
        assert detect_format(p, detect_encoding(p)) == fmt


def test_all_formats_yield_identical_canonical_records(small_dataset: dict[str, Path]) -> None:
    ref = _hashes(small_dataset["jsonl"])
    assert len(ref) > 100
    for fmt in ("csv", "json", "xml"):
        assert _hashes(small_dataset[fmt]) == ref, fmt


def test_resume_start_after(small_dataset: dict[str, Path]) -> None:
    for fmt, p in small_dataset.items():
        enc = detect_encoding(p)
        idx = [i for i, _ in iter_records(p, fmt, enc, start_after=9)]
        assert idx[0] == 10, fmt


def test_malformed_jsonl_line(tmp_path: Path) -> None:
    p = tmp_path / "x.jsonl"
    p.write_text('{"a": 1}\n{broken\n[1,2]\n')
    out = list(iter_records(p, "jsonl", "utf-8"))
    assert isinstance(out[1][1], ParseFailure) and isinstance(out[2][1], ParseFailure)
    assert out[0][1] == {"a": 1}


def test_csv_semicolon_arrays_and_extra_columns(tmp_path: Path) -> None:
    p = tmp_path / "x.csv"
    p.write_text("txid,input_addresses,input_amounts\nab,a1;a2,1;2\ncd,a3,5,EXTRA\n")
    out = list(iter_records(p, "csv", "utf-8"))
    assert out[0][1] == {"txid": "ab", "input_addresses": ["a1", "a2"], "input_amounts": ["1", "2"]}
    assert isinstance(out[1][1], ParseFailure)


def test_xml_external_entities_not_resolved(tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("TOPSECRET")
    p = tmp_path / "x.xml"
    p.write_text(
        f'<?xml version="1.0"?><!DOCTYPE t [<!ENTITY x SYSTEM "file://{secret}">]>'
        "<transactions><transaction><txid>&x;</txid></transaction></transactions>"
    )
    out = list(iter_records(p, "xml", "utf-8"))
    assert all("TOPSECRET" not in str(r) for _, r in out)


def test_latin1_encoding_detected(tmp_path: Path) -> None:
    p = tmp_path / "x.csv"
    # Encoding sniffing is heuristic; a realistic amount of text is needed for a reliable guess.
    line = "ab,Le café est fermé. Résumé de l'opération à Genève et déjà vérifié.\n"
    p.write_bytes(("txid,note\n" + line * 40).encode("latin-1"))
    enc = detect_encoding(p)
    assert enc != "utf-8"
    out = list(iter_records(p, "csv", enc))
    assert out[0][1]["note"].startswith("Le café est fermé. Résumé")
