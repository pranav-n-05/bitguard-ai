#!/usr/bin/env python3
"""Generate the deterministic SYNTHETIC BITGUARD dataset.

Usage: backend/.venv/bin/python scripts/generate_synthetic.py --seed 42 --formats jsonl,csv,json,xml
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.ingestion.synthetic import Generator  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--actors", type=int, default=300)
    p.add_argument("--baseline-tx", type=int, default=6000)
    p.add_argument("--patterns", type=int, default=6, help="instances per injected pattern type")
    p.add_argument("--error-rate", type=float, default=0.01)
    p.add_argument("--formats", default="jsonl")
    p.add_argument("--out", type=Path, default=ROOT / "ml" / "datasets" / "synthetic")
    a = p.parse_args()
    g = Generator(seed=a.seed, n_actors=a.actors, n_baseline_tx=a.baseline_tx, error_rate=a.error_rate).generate(a.patterns)
    for fmt in a.formats.split(","):
        path = g.write(a.out, fmt.strip(), name=f"bitguard_synthetic_seed{a.seed}")
        print(f"wrote {path} ({path.stat().st_size // 1024} KiB)")
    print(
        f"rows={g.labels['meta']['rows']} unique_txids={g.labels['meta']['unique_txids']} "
        f"patterns={len(g.labels['patterns'])} errors={g.labels.get('injected_errors', 0)}"
    )


if __name__ == "__main__":
    main()
