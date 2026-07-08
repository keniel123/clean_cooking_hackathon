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


def trigger_continual_update(source: str = "live", epochs: int = 5) -> dict[str, Any] | None:
    """Kick off a background retrain on ml/api and return immediately. None on failure.

    The retrain now runs asynchronously on the ML service, so this returns the
    accepted-job envelope (``status: started|already_running``) fast - it does
    not wait for training to finish. The ML service must run with
    ``GRIDCOOK_ENABLE_CONTINUAL_LEARNING=1``; otherwise it returns 403 -> None.
    """
    try:
        with _client() as client:
            response = client.post(
                "/learning/continual-update",
                params={"source": source, "epochs": epochs},
            )
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError):
        return None


def retrain_status() -> dict[str, Any] | None:
    """Current retrain job state from ml/api, or None if unavailable."""
    try:
        with _client() as client:
            response = client.get("/learning/status")
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError):
        return None
