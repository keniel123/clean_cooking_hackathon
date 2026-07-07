"""Rules-first "best time to cook" recommendation engine.

Implements the explainable MVP approach from
``docs/oloika_data_schema_and_prediction_notes.md``: aggregate the hourly grid
telemetry into a per-hour-of-day favorability score, classify each hour as
green / orange / red, and return the strongest cooking windows with a plain
explanation. No trained model is required for the demo.
"""

from __future__ import annotations

from typing import Any

from . import db, model_predictions

SLOT_GREEN = "green"
SLOT_ORANGE = "orange"
SLOT_RED = "red"

# Favorability weights. Each component is normalised to roughly 0..1 before
# weighting so the constants below express relative importance directly.
GREEN_SHARE_WEIGHT = 60.0
PV_WEIGHT = 25.0
BATTERY_SOC_WEIGHT = 15.0
LOAD_PENALTY_WEIGHT = 20.0

MAX_BATTERY_SOC_PERCENT = 100.0
DEFAULT_TOP_WINDOWS = 3

# Credit-gain model. This is the explainable rules baseline; the same schema
# (suggested_credit_gain + credit_gain_basis + model_version) is intended to be
# populated by a trained AI model later without changing the API contract.
CREDIT_MODEL_VERSION = "rules-v1"
REWARD_CREDITS_PER_KWH = 10.0
SLOT_CREDIT_MULTIPLIER = {SLOT_GREEN: 1.0, SLOT_ORANGE: 0.5, SLOT_RED: 0.0}
SHIFTED_DAYTIME_BONUS_CREDITS = 8
DAYTIME_START_HOUR = 10
DAYTIME_END_HOUR = 15
FALLBACK_SESSION_KWH = 1.0


def _pv_power_w(grid_row: dict[str, Any]) -> float:
    """Best available PV signal for an hour across the DC/AC/Fronius sources."""
    candidates = [
        grid_row.get("fronius_pv_power_w"),
        grid_row.get("pv_ac_power_w"),
        grid_row.get("pv_dc_power_w"),
    ]
    available = [value for value in candidates if value is not None]
    return max(available) if available else 0.0


def _dominant_slot_color(green: int, orange: int, red: int) -> str:
    counts = {SLOT_GREEN: green, SLOT_ORANGE: orange, SLOT_RED: red}
    return max(counts, key=counts.get)


def _explain(color: str, pv_power_w: float, battery_soc: float, load_w: float) -> str:
    solar = "high solar" if pv_power_w > 0 else "little solar"
    battery = "battery healthy" if battery_soc >= 50 else "battery low"
    if color == SLOT_GREEN:
        return f"Recommended: {solar}, {battery}, community load manageable."
    if color == SLOT_ORANGE:
        return f"Usable window, but {battery} and load headroom is moderate."
    return "Avoid if possible: grid is under stress and there is no reward now."


def _hourly_aggregates() -> dict[int, dict[str, Any]]:
    """Aggregate the 720 hourly grid rows into one summary per hour of day."""
    aggregates: dict[int, dict[str, Any]] = {}
    for row in db.select_rows("grid_hourly"):
        hour = row["hour_eat"]
        bucket = aggregates.setdefault(hour, {
            "hour_eat": hour,
            "samples": 0,
            "pv_power_w_sum": 0.0,
            "battery_soc_sum": 0.0,
            "load_w_sum": 0.0,
            "green": 0,
            "orange": 0,
            "red": 0,
        })
        bucket["samples"] += 1
        bucket["pv_power_w_sum"] += _pv_power_w(row)
        bucket["battery_soc_sum"] += row.get("battery_soc_percent") or 0.0
        bucket["load_w_sum"] += row.get("ac_load_w") or 0.0
        bucket[row["slot_color"]] += 1
    return aggregates


def _expected_kwh_by_hour() -> dict[int, float]:
    rows = db.query(
        "SELECT start_hour_eat AS hour, AVG(kwh) AS avg_kwh "
        "FROM cooking_sessions GROUP BY start_hour_eat"
    )
    return {row["hour"]: round(row["avg_kwh"], 3) for row in rows if row["avg_kwh"] is not None}


def rank_cooking_windows() -> list[dict[str, Any]]:
    """Score every hour of day and return them ranked best-first."""
    aggregates = _hourly_aggregates()
    if not aggregates:
        return []

    hourly_pv = {hour: bucket["pv_power_w_sum"] / bucket["samples"]
                 for hour, bucket in aggregates.items()}
    hourly_load = {hour: bucket["load_w_sum"] / bucket["samples"]
                   for hour, bucket in aggregates.items()}
    peak_pv = max(hourly_pv.values()) or 1.0
    peak_load = max(hourly_load.values()) or 1.0
    expected_kwh = _expected_kwh_by_hour()

    windows: list[dict[str, Any]] = []
    for hour, bucket in aggregates.items():
        samples = bucket["samples"]
        avg_pv = hourly_pv[hour]
        avg_soc = bucket["battery_soc_sum"] / samples
        avg_load = hourly_load[hour]
        green_share = bucket["green"] / samples
        color = _dominant_slot_color(bucket["green"], bucket["orange"], bucket["red"])

        score = (
            GREEN_SHARE_WEIGHT * green_share
            + PV_WEIGHT * (avg_pv / peak_pv)
            + BATTERY_SOC_WEIGHT * (avg_soc / MAX_BATTERY_SOC_PERCENT)
            - LOAD_PENALTY_WEIGHT * (avg_load / peak_load)
        )

        windows.append({
            "hour_eat": hour,
            "window": f"{hour:02d}:00-{(hour + 1) % 24:02d}:00",
            "slot_color": color,
            "favorability_score": round(score, 2),
            "green_window_share": round(green_share, 3),
            "avg_pv_power_w": round(avg_pv, 1),
            "avg_battery_soc_percent": round(avg_soc, 1),
            "avg_load_w": round(avg_load, 1),
            "expected_kwh": expected_kwh.get(hour),
            "reason": _explain(color, avg_pv, avg_soc, avg_load),
        })

    windows.sort(key=lambda window: window["favorability_score"], reverse=True)
    return windows


def top_cooking_windows(top: int = DEFAULT_TOP_WINDOWS) -> list[dict[str, Any]]:
    return rank_cooking_windows()[:top]


def _is_shifted_daytime(hour: int, slot_color: str) -> bool:
    in_daytime = DAYTIME_START_HOUR <= hour <= DAYTIME_END_HOUR
    return in_daytime and slot_color != SLOT_RED


def estimate_credit_gain(slot_color: str, expected_kwh: float, hour: int) -> dict[str, Any]:
    """Estimate reward credits for cooking a session in the given hour.

    Placeholder for the AI credit model; keeps the schema stable. Reward scales
    with energy and slot color, plus a daytime-shift bonus that mirrors the
    leaderboard incentive in the dataset docs.
    """
    multiplier = SLOT_CREDIT_MULTIPLIER.get(slot_color, 0.0)
    energy_credits = expected_kwh * REWARD_CREDITS_PER_KWH * multiplier
    shift_bonus = SHIFTED_DAYTIME_BONUS_CREDITS if _is_shifted_daytime(hour, slot_color) else 0
    suggested = int(round(energy_credits)) + shift_bonus
    basis = (
        f"{slot_color} window x{multiplier:g} on {expected_kwh:.2f} kWh"
        + (f" + {shift_bonus} daytime-shift bonus" if shift_bonus else "")
    )
    return {
        "suggested_credit_gain": suggested,
        "credit_gain_basis": basis,
        "model_version": CREDIT_MODEL_VERSION,
    }


def assess_cooking_time(hour: int, planned_duration_minutes: float | None = None) -> dict[str, Any]:
    """Assess a user-chosen cooking hour and return slot, energy, and credit gain."""
    ranked = rank_cooking_windows()
    by_hour = {window["hour_eat"]: window for window in ranked}
    window = by_hour.get(hour)

    if window is None:
        slot_color = SLOT_RED
        expected_kwh = FALLBACK_SESSION_KWH
        reason = "No grid history for this hour; treated as an off-peak window."
    else:
        slot_color = window["slot_color"]
        expected_kwh = window["expected_kwh"] or FALLBACK_SESSION_KWH
        reason = window["reason"]

    credit = estimate_credit_gain(slot_color, expected_kwh, hour)

    # Prefer the trained model's prediction when apps/model has exported one;
    # otherwise keep the rules-v1 result computed above.
    prediction = model_predictions.hour_prediction(hour)
    if prediction is not None:
        slot_color = prediction["slot_color"]
        expected_kwh = prediction["expected_kwh"]
        reason = f"Model prediction ({prediction['model_version']}) for this hour."
        credit = {
            "suggested_credit_gain": prediction["suggested_credit_gain"],
            "credit_gain_basis": prediction["credit_gain_basis"],
            "model_version": prediction["model_version"],
        }

    best_window = ranked[0] if ranked else None
    is_optimal = bool(best_window and hour == best_window["hour_eat"])

    return {
        "requested_hour_eat": hour,
        "window": f"{hour:02d}:00-{(hour + 1) % 24:02d}:00",
        "slot_color": slot_color,
        "expected_kwh": round(expected_kwh, 3),
        "planned_duration_minutes": planned_duration_minutes,
        "reason": reason,
        "is_optimal": is_optimal,
        "best_alternative": None if is_optimal else best_window,
        **credit,
    }
