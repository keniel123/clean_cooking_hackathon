"""HTTP client for the live ML serving API (``ml/api``).

Keeps ``apps/api`` torch-free: it calls the model service over HTTP for live
predictions. Every method returns ``None`` on any failure so callers can fall
back to the cached export and then the rules baseline without branching on
transport details.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

ML_API_URL = os.environ.get("GRIDCOOK_ML_API_URL", "http://127.0.0.1:8100")
ML_API_TIMEOUT_SECONDS = float(os.environ.get("GRIDCOOK_ML_API_TIMEOUT", "3.0"))


def _client() -> httpx.Client:
    return httpx.Client(base_url=ML_API_URL, timeout=ML_API_TIMEOUT_SECONDS)


def plan(account_id: str, hour: int, date: str = "2025-06-15",
         cooker_id: str | None = None,
         planned_duration_minutes: float | None = None) -> dict[str, Any] | None:
    """Live per-(account, hour) score from the model, or None if unavailable."""
    body: dict[str, Any] = {"account_id": account_id, "date": date, "start_hour_eat": hour}
    if cooker_id is not None:
        body["cooker_id"] = cooker_id
    if planned_duration_minutes is not None:
        body["planned_duration_minutes"] = planned_duration_minutes
    try:
        with _client() as client:
            response = client.post("/plans", json=body)
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError):
        return None


def account_recommendations(account_id: str, top: int = 24) -> dict[str, Any] | None:
    """Live per-account 24-hour recommendation set, or None if unavailable."""
    try:
        with _client() as client:
            response = client.get(f"/accounts/{account_id}/recommendations", params={"top": top})
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError):
        return None


def community_hours() -> dict[int, dict[str, Any]] | None:
    """Live grid-level per-hour model view as ``{hour: row}``, or None if unavailable."""
    try:
        with _client() as client:
            response = client.get("/recommendations/hourly")
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    hours = payload.get("hours")
    if not hours:
        return None
    return {int(row["hour_eat"]): row for row in hours}


# Retrains can take a while; use a longer timeout than the read calls.
RETRAIN_TIMEOUT_SECONDS = float(os.environ.get("GRIDCOOK_ML_RETRAIN_TIMEOUT", "600"))


def trigger_continual_update(source: str = "live", epochs: int = 5) -> dict[str, Any] | None:
    """Ask ml/api to retrain from accumulated live sessions. None on failure.

    The ML service must run with ``GRIDCOOK_ENABLE_CONTINUAL_LEARNING=1`` to
    accept this; otherwise it returns 403 and this returns None.
    """
    try:
        with httpx.Client(base_url=ML_API_URL, timeout=RETRAIN_TIMEOUT_SECONDS) as client:
            response = client.post(
                "/learning/continual-update",
                params={"source": source, "epochs": epochs},
            )
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError):
        return None
