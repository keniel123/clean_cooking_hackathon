"""CLI wrapper for the replay-based continual update.

The reusable logic lives in ``gridcook_model.training.continual_update`` so the
live ML service can run it in-process. This script is for offline / manual runs.

    python3 scripts/ingest_new_data.py --source live --epochs 5
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gridcook_model.training.continual_update import DEFAULT_CUTOFF, run_update


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=["cutoff", "live"], default="cutoff",
                        help="'live': learn from API-recorded sessions; 'cutoff': simulate from history")
    parser.add_argument("--cutoff", default=DEFAULT_CUTOFF, help="Boundary between history and new data")
    parser.add_argument("--epochs", type=int, default=15)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    decision = run_update(source=args.source, cutoff=args.cutoff, epochs=args.epochs, seed=args.seed)
    print(json.dumps(decision, indent=2))


if __name__ == "__main__":
    main()
