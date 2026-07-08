from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


ML_ROOT = Path(__file__).resolve().parents[1]
PYTHON = ML_ROOT / ".venv" / "bin" / "python"


def main() -> None:
    parser = argparse.ArgumentParser(description="Train all GridCook ML models and export personalized predictions.")
    parser.add_argument("--epochs", type=int, default=60)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--cutoff", default="2025-06-23")
    args = parser.parse_args()

    subprocess.run(
        [
            str(PYTHON),
            "scripts/train_all.py",
            "--epochs",
            str(args.epochs),
            "--seed",
            str(args.seed),
            "--cutoff",
            args.cutoff,
        ],
        cwd=ML_ROOT,
        check=True,
    )
    subprocess.run([str(PYTHON), "scripts/export_for_api.py"], cwd=ML_ROOT, check=True)
    subprocess.run([str(PYTHON), "scripts/audit_models.py"], cwd=ML_ROOT, check=True)


if __name__ == "__main__":
    main()
