from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import torch


REPO_ROOT = Path(__file__).resolve().parents[2]
ML_ROOT = REPO_ROOT / "ml"
CHECKPOINT_ROOT = ML_ROOT / "checkpoints"
EXPORT_PATHS = [
    ML_ROOT / "exports" / "nn_predictions.json",
]
REPORT_PATH = ML_ROOT / "reports" / "model_audit.json"

MODEL_FILES = {
    "grid_forecaster": "ml/gridcook_model/models/grid_forecaster.py",
    "risk_classifier": "ml/gridcook_model/models/risk_classifier.py",
    "demand_forecaster": "ml/gridcook_model/models/demand_forecaster.py",
    "recommender": "ml/gridcook_model/models/recommender.py",
}


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def checkpoint_status(model_name: str) -> dict[str, Any]:
    model_dir = CHECKPOINT_ROOT / model_name
    manifest = load_json(model_dir / "manifest.json")
    status: dict[str, Any] = {
        "model_file": MODEL_FILES[model_name],
        "has_manifest": manifest is not None,
        "current": manifest.get("current") if manifest else None,
        "versions": manifest.get("versions", []) if manifest else [],
        "trained": False,
        "metrics": {},
        "checkpoint_path": None,
    }
    current = status["current"]
    if current:
        checkpoint = model_dir / f"{current}.pt"
        status["checkpoint_path"] = str(checkpoint.relative_to(REPO_ROOT))
        status["trained"] = checkpoint.exists()
        if checkpoint.exists():
            payload = torch.load(checkpoint, map_location="cpu", weights_only=False)
            status["model_class"] = payload.get("model_class")
            status["metrics"] = payload.get("metadata", {}).get("metrics", {})
            status["feature_columns"] = payload.get("metadata", {}).get("feature_columns", [])
    return status


def export_status() -> dict[str, Any]:
    for path in EXPORT_PATHS:
        if not path.exists():
            continue
        data = load_json(path) or {}
        return {
            "exists": True,
            "path": str(path.relative_to(REPO_ROOT)),
            "model_version": data.get("model_version"),
            "generated_hours": len(data.get("generated_hours", {})),
            "account_hours": len(data.get("account_hours", {})),
            "generated_at": data.get("generated_at"),
        }
    return {"exists": False, "path": None}


def verdict(models: dict[str, dict[str, Any]]) -> dict[str, str]:
    result = {}
    result["risk_classifier"] = "use" if models["risk_classifier"]["trained"] else "missing"
    result["recommender"] = "use" if models["recommender"]["trained"] else "missing"
    result["grid_forecaster"] = "supporting" if models["grid_forecaster"]["trained"] else "missing"
    demand = models["demand_forecaster"]
    demand_metrics = demand.get("metrics", {})
    demand_mae = demand_metrics.get("test_mae")
    baseline = demand_metrics.get("baseline_hour_of_day_mae")
    if not demand["trained"]:
        result["demand_forecaster"] = "missing"
    elif demand_mae is not None and baseline is not None and demand_mae > baseline:
        result["demand_forecaster"] = "experimental_baseline_better"
    else:
        result["demand_forecaster"] = "use"
    return result


def main() -> None:
    models = {name: checkpoint_status(name) for name in MODEL_FILES}
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "all_modules_have_checkpoints": all(model["trained"] for model in models.values()),
        "models": models,
        "export": export_status(),
        "verdict": verdict(models),
        "notes": [
            "The recommender and risk classifier are the main hackathon models.",
            "The demand forecaster is trained but currently underperforms the hour-of-day baseline.",
            "Do not claim production readiness: the dataset has one real month plus synthetic account/persona fill.",
        ],
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    print(f"\nWrote {REPORT_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    sys.path.insert(0, str(ML_ROOT))
    main()
