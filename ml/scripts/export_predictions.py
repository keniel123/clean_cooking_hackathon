from __future__ import annotations

import subprocess
from pathlib import Path


ML_ROOT = Path(__file__).resolve().parents[1]
PYTHON = ML_ROOT / ".venv" / "bin" / "python"


def main() -> None:
    subprocess.run([str(PYTHON), "scripts/export_for_api.py"], cwd=ML_ROOT, check=True)


if __name__ == "__main__":
    main()
