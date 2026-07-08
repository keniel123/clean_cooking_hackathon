"""Live shared-grid capacity coordination.

The recommender predicts favorable windows from historical community + grid
patterns, but it does not know what the rest of the community has *already*
committed today. This module closes that gap: it reads the committed load for a
date (bookings + live sessions), compares it to the per-hour available capacity
of the single shared mini-grid, and adjusts each recommended window so users are
steered away from hours that are filling up.

Kept deliberately torch-free and rules-based: it overlays on top of whatever the
model produced without changing the model itself.
"""

from __future__ import annotations

import os
from typing import Any

from . import db, scoring

SLOT_GREEN = "green"
SLOT_ORANGE = "orange"
SLOT_RED = "red"
_DOWNGRADE = {SLOT_GREEN: SLOT_ORANGE, SLOT_ORANGE: SLOT_RED, SLOT_RED: SLOT_RED}
_SLOT_RANK = {SLOT_GREEN: 2, SLOT_ORANGE: 1, SLOT_RED: 0}

# Committed statuses that count against the shared grid for a booking.
_ACTIVE_PLAN_STATUSES = ("planned", "confirmed")

# Utilisation thresholds: below WARN keep the model's color; between WARN and
# FULL downgrade one step; at/above FULL (or the concurrent-cooker cap) the hour
# is treated as full (red).
WARN_UTILISATION = float(os.environ.get("GRIDCOOK_CAPACITY_WARN_UTIL", "0.6"))
FULL_UTILISATION = float(os.environ.get("GRIDCOOK_CAPACITY_FULL_UTIL", "0.85"))

# Base cooking capacity of the shared grid per hour, scaled per-hour by the
# historical solar/battery availability so midday (high PV) allows more load.
GRID_CAPACITY_KWH_PER_HOUR = float(os.environ.get("GRIDCOOK_GRID_CAPACITY_KWH", "12.0"))
CAPACITY_SAFETY_MARGIN_KWH = float(os.environ.get("GRIDCOOK_CAPACITY_SAFETY_KWH", "1.0"))
MAX_CONCURRENT_COOKERS = int(os.environ.get("GRIDCOOK_MAX_CONCURRENT_COOKERS", "8"))

_MIN_AVAILABILITY_FACTOR = 0.4
_MAX_AVAILABILITY_FACTOR = 1.2


def _availability_factor_by_hour() -> dict[int, float]:
    """Per-hour multiplier in [0.4, 1.2] from historical PV + battery health.

    Hours with more solar and a healthier battery can host more cooking load.
    """
    aggregates = scoring._hourly_aggregates()
    if not aggregates:
        return {}
    pv_by_hour = {hour: bucket["pv_power_w_sum"] / bucket["samples"]
                  for hour, bucket in aggregates.items()}
    soc_by_hour = {hour: bucket["battery_soc_sum"] / bucket["samples"]
                   for hour, bucket in aggregates.items()}
    peak_pv = max(pv_by_hour.values()) or 1.0

    factors: dict[int, float] = {}
    for hour in aggregates:
        pv_component = pv_by_hour[hour] / peak_pv
        soc_component = soc_by_hour[hour] / scoring.MAX_BATTERY_SOC_PERCENT
        raw = 0.5 * pv_component + 0.5 * soc_component
        factors[hour] = _MIN_AVAILABILITY_FACTOR + raw * (
            _MAX_AVAILABILITY_FACTOR - _MIN_AVAILABILITY_FACTOR
        )
    return factors


def capacity_kwh_by_hour() -> dict[int, float]:
    """Usable cooking capacity per hour after the safety margin."""
    factors = _availability_factor_by_hour()
    capacity: dict[int, float] = {}
    for hour in range(24):
        factor = factors.get(hour, 1.0)
        usable = GRID_CAPACITY_KWH_PER_HOUR * factor - CAPACITY_SAFETY_MARGIN_KWH
        capacity[hour] = max(usable, 0.0)
    return capacity


def committed_load(date: str) -> dict[int, dict[str, float]]:
    """Committed kWh and cooker count per hour for a date.

    Combines bookings (``cooking_plans``) and actual usage
    (``cooking_sessions_live``) so both a plan and a running session count.
    """
    committed: dict[int, dict[str, float]] = {
        hour: {"kwh": 0.0, "cookers": 0} for hour in range(24)
    }

    placeholders = ", ".join("?" for _ in _ACTIVE_PLAN_STATUSES)
    plan_rows = db.query(
        "SELECT start_hour_eat AS hour, COUNT(*) AS cookers, "
        "COALESCE(SUM(expected_kwh), 0) AS kwh FROM cooking_plans "
        f"WHERE date = ? AND status IN ({placeholders}) GROUP BY start_hour_eat",
        [date, *_ACTIVE_PLAN_STATUSES],
    )
    session_rows = db.query(
        "SELECT start_hour_eat AS hour, COUNT(*) AS cookers, "
        "COALESCE(SUM(kwh), 0) AS kwh FROM cooking_sessions_live "
        "WHERE date = ? GROUP BY start_hour_eat",
        [date],
    )
    for row in (*plan_rows, *session_rows):
        hour = int(row["hour"])
        committed[hour]["kwh"] += float(row["kwh"] or 0.0)
        committed[hour]["cookers"] += int(row["cookers"] or 0)
    return committed


def hour_state(date: str, hour: int) -> dict[str, float]:
    """Capacity, committed load, headroom, and utilisation for one (date, hour)."""
    capacity = capacity_kwh_by_hour().get(hour, 0.0)
    load = committed_load(date).get(hour, {"kwh": 0.0, "cookers": 0})
    committed_kwh = load["kwh"]
    headroom = max(capacity - committed_kwh, 0.0)
    utilisation = committed_kwh / capacity if capacity > 0 else 1.0
    return {
        "capacity_kwh": round(capacity, 3),
        "committed_kwh": round(committed_kwh, 3),
        "headroom_kwh": round(headroom, 3),
        "utilisation": round(utilisation, 3),
        "cookers": int(load["cookers"]),
    }


def _apply_state(window: dict[str, Any], state: dict[str, float]) -> dict[str, Any]:
    """Return a capacity-adjusted copy of a recommendation window."""
    adjusted = dict(window)
    utilisation = state["utilisation"]
    color = window.get("slot_color", SLOT_RED)

    full = (
        state["cookers"] >= MAX_CONCURRENT_COOKERS
        or utilisation >= FULL_UTILISATION
        or state["headroom_kwh"] <= 0.0
    )
    if full:
        color = SLOT_RED
    elif utilisation >= WARN_UTILISATION:
        color = _DOWNGRADE[color]

    # Keep the model's smart reward but apply live scarcity: an hour with lots of
    # headroom pays full, a nearly-full hour pays less, and a hour pushed off
    # green by committed load earns nothing.
    model_reward = float(window.get("suggested_credit_gain", 0.0) or 0.0)
    if color != SLOT_GREEN:
        credit = 0.0
        note = "Shared grid is full for this hour - pick a window with headroom." if full \
            else "Downgraded by committed load - earns no credit."
    else:
        capacity = state["capacity_kwh"] or 1.0
        headroom_fraction = max(min(state["headroom_kwh"] / capacity, 1.0), 0.0)
        scarcity_factor = 0.5 + 0.5 * headroom_fraction
        credit = round(min(model_reward * scarcity_factor, 1.0), 3)
        note = (
            f"Capacity-adjusted x{scarcity_factor:.2f}: {state['cookers']} cooker(s), "
            f"{state['headroom_kwh']:.1f} kWh headroom."
        )

    adjusted["slot_color"] = color
    adjusted["suggested_credit_gain"] = credit
    adjusted["capacity_utilisation"] = state["utilisation"]
    adjusted["headroom_kwh"] = state["headroom_kwh"]
    adjusted["committed_kwh"] = state["committed_kwh"]
    adjusted["committed_cookers"] = state["cookers"]
    adjusted["capacity_note"] = note
    return adjusted


def adjust_windows(windows: list[dict[str, Any]], date: str) -> list[dict[str, Any]]:
    """Overlay live capacity on a list of hour windows (does not re-sort)."""
    capacity = capacity_kwh_by_hour()
    load = committed_load(date)
    adjusted: list[dict[str, Any]] = []
    for window in windows:
        hour = int(window["hour_eat"])
        cap = capacity.get(hour, 0.0)
        committed_kwh = load.get(hour, {"kwh": 0.0})["kwh"]
        cookers = load.get(hour, {"cookers": 0})["cookers"]
        headroom = max(cap - committed_kwh, 0.0)
        state = {
            "capacity_kwh": round(cap, 3),
            "committed_kwh": round(committed_kwh, 3),
            "headroom_kwh": round(headroom, 3),
            "utilisation": round(committed_kwh / cap if cap > 0 else 1.0, 3),
            "cookers": int(cookers),
        }
        adjusted.append(_apply_state(window, state))
    return adjusted


def rank_key(window: dict[str, Any]) -> tuple:
    """Sort key so windows with headroom, better color, and more credit come first."""
    return (
        _SLOT_RANK.get(window.get("slot_color"), 0),
        float(window.get("suggested_credit_gain", 0.0) or 0.0),
        window.get("headroom_kwh", 0.0),
        -int(window["hour_eat"]),
    )


def adjust_and_rank(windows: list[dict[str, Any]], date: str) -> list[dict[str, Any]]:
    """Capacity-adjust and re-rank windows best-first for the shared grid."""
    adjusted = adjust_windows(windows, date)
    return sorted(adjusted, key=rank_key, reverse=True)
