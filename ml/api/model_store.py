"""Live model access for the ML serving API.

The trained recommender checkpoint is loaded into memory once (lazy singleton)
and run per request via ``RecommenderService.predict`` - this is genuine live
inference, not a precomputed file. Per-account calls run a fresh forward pass;
the community per-hour view is computed once and cached because the historical
dataset it averages over is static.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from gridcook_model.data import features
from gridcook_model.serving import RecommenderService
from gridcook_model.serving.inference import HOURS_PER_DAY

from . import data_store

REPO_ROOT = Path(__file__).resolve().parents[2]
AUDIT_PATH = REPO_ROOT / "ml" / "reports" / "model_audit.json"

_service: RecommenderService | None = None
_service_loaded = False
_community_cache: dict[str, Any] | None = None
_audit_cache: dict[str, Any] | None = None


def service() -> RecommenderService | None:
    """Return the loaded recommender, or None if no checkpoint is available."""
    global _service, _service_loaded
    if not _service_loaded:
        _service_loaded = True
        try:
            _service = RecommenderService()
        except Exception:
            _service = None
    return _service


def reload() -> str | None:
    """Drop cached model + derived views so the next call serves the newest checkpoint.

    Called after a continual-learning update promotes a new version, giving the
    running service genuine hot-reload without a restart.
    """
    global _service, _service_loaded, _community_cache, _audit_cache
    _service = None
    _service_loaded = False
    _community_cache = None
    _audit_cache = None
    return model_version()


def model_version() -> str | None:
    svc = service()
    return svc.model_version if svc else None


def prediction(account_id: str, hour: int) -> dict[str, Any] | None:
    """Live per-(account, hour) prediction via a fresh forward pass."""
    svc = service()
    if svc is None:
        return None
    return svc.predict(account_id, hour)


def community_hours() -> dict[str, Any]:
    """Grid-level per-hour view (account-averaged), computed live once and cached."""
    global _community_cache
    if _community_cache is not None:
        return _community_cache

    svc = service()
    if svc is None:
        _community_cache = {}
        return _community_cache

    account_ids = [row["account_id"] for row in data_store.accounts()]
    hours: dict[str, Any] = {}
    for hour in range(HOURS_PER_DAY):
        slot_votes = np.zeros(len(features.SLOT_COLORS))
        kwh_values: list[float] = []
        reward_values: list[float] = []
        for account_id in account_ids:
            predicted = svc.predict(account_id, hour)
            if predicted is None:
                continue
            slot_votes[features.SLOT_TO_INDEX[predicted["slot_color"]]] += 1
            kwh_values.append(predicted["expected_kwh"])
            reward_values.append(predicted["suggested_credit_gain"])
        if not kwh_values:
            continue
        slot_color = features.INDEX_TO_SLOT[int(slot_votes.argmax())]
        expected_kwh = round(float(np.mean(kwh_values)), 3)
        # Community credit = average smart reward across accounts for this hour.
        suggested = round(float(np.mean(reward_values)), 3)
        hours[str(hour)] = {
            "slot_color": slot_color,
            "expected_kwh": expected_kwh,
            "suggested_credit_gain": suggested,
            "credit_gain_basis": f"community avg smart reward ({slot_color})",
            "model_version": svc.model_version,
        }

    _community_cache = {"model_version": svc.model_version, "generated_hours": hours}
    return _community_cache


def audit() -> dict[str, Any]:
    global _audit_cache
    if _audit_cache is None:
        if AUDIT_PATH.exists():
            _audit_cache = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
        else:
            _audit_cache = {}
    return _audit_cache
