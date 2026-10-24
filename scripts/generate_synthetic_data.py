"""Write the synthetic prescribing data used for the anomaly model to CSV files (Phase 8).

Usage: python scripts/generate_synthetic_data.py [--out data/synthetic] [--seed 42]
The data is entirely made up (see app/ai/synthetic.py). train_anomaly.py generates the same data
itself; this script exists so the data can be inspected, plotted or reused.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ai import synthetic  # noqa: E402
from app.ai.features import FEATURE_NAMES  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data/synthetic")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    data = synthetic.generate(seed=args.seed)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for split, rows in data.items():
        with open(out / f"{split}.csv", "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["family", "doctor", *FEATURE_NAMES, "medicines"])
            for row in rows:
                writer.writerow(
                    [
                        row.family,
                        row.doctor,
                        *(row.features[n] for n in FEATURE_NAMES),
                        json.dumps(row.medicines),
                    ]
                )
        print(f"{split:12s} {len(rows):5d} rows -> {out / (split + '.csv')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
