"""Optional consumer of the trained model export (nn-v1).

If the model app (``apps/model``) has exported per-hour predictions, the API
surfaces them; otherwise every caller falls back to the rules baseline. This
keeps the API torch-free: it only reads a small JSON artifact.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# apps/api/gridcook/model_predictions.py -> repo root is three parents up.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_EXPORT = _REPO_ROOT / "apps" / "model" / "exports" / "nn_predictions.json"

_cache: dict[str, Any] = {"mtime": None, "data": None}


def _export_path() -> Path:
    override = os.environ.get("GRIDCOOK_MODEL_EXPORT")
    return Path(override) if override else _DEFAULT_EXPORT


def _load() -> dict[str, Any] | None:
    path = _export_path()
    if not path.exists():
        return None
    mtime = path.stat().st_mtime
    if _cache["mtime"] != mtime:
        _cache["data"] = json.loads(path.read_text(encoding="utf-8"))
        _cache["mtime"] = mtime
    return _cache["data"]


def hour_prediction(hour: int) -> dict[str, Any] | None:
    """Return the exported prediction for an hour, or None if unavailable."""
    data = _load()
    if not data:
        return None
    entry = data.get("generated_hours", {}).get(str(hour))
    if entry is None:
        return None
    return {**entry, "model_version": data.get("model_version", "nn")}
