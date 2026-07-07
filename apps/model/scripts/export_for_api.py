"""Export the trained recommender's per-hour predictions for the API to serve.

Writes a compact JSON artifact so the API can surface ``nn-v1`` credit
recommendations without importing torch. If no artifact exists, the API falls
back to its ``rules-v1`` logic.

    python3 scripts/export_for_api.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gridcook_model.registry import latest_version
from gridcook_model.serving import build_hourly_table

_MODEL_DIR = Path(__file__).resolve().parents[1]
_DEFAULT_EXPORT = _MODEL_DIR / "exports" / "nn_predictions.json"


def export_path() -> Path:
    override = os.environ.get("GRIDCOOK_MODEL_EXPORT")
    return Path(override) if override else _DEFAULT_EXPORT


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()

    if latest_version("recommender") is None:
        raise SystemExit("No recommender checkpoint found. Run scripts/train_all.py first.")

    table = build_hourly_table()
    table["generated_at"] = datetime.now(timezone.utc).isoformat()

    destination = export_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(table, indent=2), encoding="utf-8")

    print(f"Exported {len(table['generated_hours'])} hourly predictions "
          f"({table['model_version']}) to {destination}")


if __name__ == "__main__":
    main()
