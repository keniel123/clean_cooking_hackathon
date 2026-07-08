from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


ML_ROOT = Path(__file__).resolve().parents[1]
PYTHON = ML_ROOT / ".venv" / "bin" / "python"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run replay-based continual learning and export the promoted model.")
    parser.add_argument("--source", choices=["cutoff", "live"], default="cutoff")
    parser.add_argument("--cutoff", default="2025-06-23")
    parser.add_argument("--epochs", type=int, default=15)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    subprocess.run(
        [
            str(PYTHON),
            "scripts/ingest_new_data.py",
            "--source",
            args.source,
            "--cutoff",
            args.cutoff,
            "--epochs",
            str(args.epochs),
            "--seed",
            str(args.seed),
        ],
        cwd=ML_ROOT,
        check=True,
    )
    subprocess.run([str(PYTHON), "scripts/export_for_api.py"], cwd=ML_ROOT, check=True)
    subprocess.run([str(PYTHON), "scripts/audit_models.py"], cwd=ML_ROOT, check=True)


if __name__ == "__main__":
    main()
