from __future__ import annotations

import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from . import data_store, model_store


REPO_ROOT = Path(__file__).resolve().parents[2]

app = FastAPI(
    title="GridCook ML Serving API",
    version="0.1.0",
    description="Small API focused only on model status, account recommendations, plan scoring, and continual-learning demo updates.",
)


class CookingPlanRequest(BaseModel):
    account_id: str = Field(..., examples=["HH-0007"])
    date: str = Field(..., examples=["2025-06-15"])
    start_hour_eat: int = Field(..., ge=0, le=23)
    cooker_id: str | None = None
    planned_duration_minutes: float | None = Field(None, gt=0)


def _window(hour: int) -> str:
    return f"{hour:02d}:00-{(hour + 1) % 24:02d}:00"


def _recommendation_row(account_id: str, hour: int) -> dict[str, Any]:
    prediction = model_store.prediction(account_id, hour)
    if prediction is None:
        raise HTTPException(
            status_code=503,
            detail="No trained recommender checkpoint found. Run python3 ml/scripts/run_training_pipeline.py",
        )
    return {
        "account_id": account_id,
        "hour_eat": hour,
        "window": _window(hour),
        **prediction,
    }


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "model_version": model_store.model_version(),
        "live_inference": model_store.service() is not None,
        "accounts": len(data_store.accounts()),
    }


@app.get("/model/status")
def model_status() -> dict[str, Any]:
    community = model_store.community_hours()
    return {
        "model_version": model_store.model_version(),
        "live_inference": model_store.service() is not None,
        "community_hours": len(community.get("generated_hours", {})),
        "audit": model_store.audit(),
    }


@app.get("/recommendations/hourly")
def community_recommendations() -> dict[str, Any]:
    """Grid-level per-hour recommendation (account-averaged live model output)."""
    community = model_store.community_hours()
    generated = community.get("generated_hours", {})
    if not generated:
        raise HTTPException(
            status_code=503,
            detail="No trained recommender checkpoint found. Run python3 ml/scripts/run_training_pipeline.py",
        )
    hours = [
        {"hour_eat": int(hour), "window": _window(int(hour)), **row}
        for hour, row in sorted(generated.items(), key=lambda item: int(item[0]))
    ]
    return {"model_version": community.get("model_version"), "count": len(hours), "hours": hours}


@app.get("/accounts/{account_id}/profile")
def account_profile(account_id: str) -> dict[str, Any]:
    profile = data_store.account_profile(account_id)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"Unknown account_id: {account_id}")
    return profile


@app.get("/accounts/{account_id}/recommendations")
def account_recommendations(account_id: str, top: int = Query(24, ge=1, le=24)) -> dict[str, Any]:
    if data_store.get_account(account_id) is None:
        raise HTTPException(status_code=404, detail=f"Unknown account_id: {account_id}")
    all_windows = [_recommendation_row(account_id, hour) for hour in range(24)]
    ranked = sorted(
        all_windows,
        key=lambda row: (
            int(row["suggested_credit_gain"]),
            1 if row["slot_color"] == "green" else 0,
            -row["hour_eat"],
        ),
        reverse=True,
    )
    return {
        "account_id": account_id,
        "model_version": all_windows[0]["model_version"] if all_windows else None,
        "all_windows": all_windows,
        "recommended_windows": ranked[:top],
    }


@app.post("/plans", status_code=201)
def score_cooking_plan(plan: CookingPlanRequest) -> dict[str, Any]:
    if data_store.get_account(plan.account_id) is None:
        raise HTTPException(status_code=404, detail=f"Unknown account_id: {plan.account_id}")
    if not data_store.known_cooker(plan.account_id, plan.cooker_id):
        raise HTTPException(status_code=400, detail="Cooker does not belong to the account")
    recommendation = _recommendation_row(plan.account_id, plan.start_hour_eat)
    return {
        "plan_id": f"PLAN-{uuid.uuid4().hex[:8]}",
        "date": plan.date,
        "cooker_id": plan.cooker_id,
        "planned_duration_minutes": plan.planned_duration_minutes,
        "created_at": datetime.now(timezone.utc).isoformat(),
        **recommendation,
    }


@app.get("/leaderboard")
def leaderboard(limit: int = Query(10, ge=1, le=84)) -> dict[str, Any]:
    rows = sorted(data_store.leaderboard(), key=lambda row: int(row["rank"]))[:limit]
    return {"count": len(rows), "results": rows}


@app.post("/learning/continual-update")
def continual_update(
    source: str = Query("live", pattern="^(live|cutoff)$"),
    cutoff: str = "2025-06-23",
    epochs: int = Query(5, ge=1, le=60),
) -> dict[str, Any]:
    """Retrain the recommender from newly funneled data, then hot-reload it.

    ``source=live`` learns from sessions the product API recorded; ``cutoff``
    simulates new data from history. Guarded by an env flag so it cannot be
    triggered by accident.
    """
    if os.environ.get("GRIDCOOK_ENABLE_CONTINUAL_LEARNING") != "1":
        raise HTTPException(
            status_code=403,
            detail="Set GRIDCOOK_ENABLE_CONTINUAL_LEARNING=1 to allow model updates from the API.",
        )
    previous_version = model_store.model_version()
    result = subprocess.run(
        [
            "python3",
            "ml/scripts/run_continual_update.py",
            "--source",
            source,
            "--cutoff",
            cutoff,
            "--epochs",
            str(epochs),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail={"stdout": result.stdout, "stderr": result.stderr})

    new_version = model_store.reload()
    return {
        "returncode": result.returncode,
        "source": source,
        "previous_version": previous_version,
        "model_version": new_version,
        "promoted": new_version != previous_version,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "model_status": model_status(),
    }
