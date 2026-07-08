"""Rules-first "best time to cook" recommendation engine.

Implements the explainable MVP approach from
``docs/oloika_data_schema_and_prediction_notes.md``: aggregate the hourly grid
telemetry into a per-hour-of-day favorability score, classify each hour as
green / orange / red, and return the strongest cooking windows with a plain
explanation. No trained model is required for the demo.
"""

from __future__ import annotations

from typing import Any

from . import db, ml_client, model_predictions

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

# Credit-gain model. Fallback for when the live ML service is unavailable: it
# mirrors the model's smart reward using hourly aggregates instead of learned
# outputs. Only green windows earn credit; the amount scales with how reliably
# green the hour is and how much it benefits the grid. Whole credits are realized
# by accumulation, not per session (see db.award_session_credit).
CREDIT_MODEL_VERSION = "rules-v1"
BASE_REWARD = 0.2
MAX_SESSION_CREDIT = 1.0
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

    _overlay_model(windows)
    windows.sort(key=lambda window: window["favorability_score"], reverse=True)
    return windows


def _overlay_model(windows: list[dict[str, Any]]) -> None:
    """Attach credit fields to each window, preferring model output over rules.

    Grid ordering (favorability_score) is left untouched; only the surfaced
    slot color, expected kWh, credit, and model_version reflect the model when a
    prediction is available, otherwise the rules baseline fills them in.
    """
    community = ml_client.community_hours() or {}
    for window in windows:
        hour = window["hour_eat"]
        model_row = community.get(hour) or model_predictions.hour_prediction(hour)
        if model_row is not None:
            window["slot_color"] = model_row["slot_color"]
            window["expected_kwh"] = model_row["expected_kwh"]
            window["reason"] = f"Model prediction ({model_row['model_version']}) for this hour."
            window["suggested_credit_gain"] = model_row["suggested_credit_gain"]
            window["credit_gain_basis"] = model_row["credit_gain_basis"]
            window["model_version"] = model_row["model_version"]
            continue
        kwh = window["expected_kwh"] if window["expected_kwh"] is not None else FALLBACK_SESSION_KWH
        window.update(estimate_credit_gain(window["slot_color"], kwh, hour))


def top_cooking_windows(top: int = DEFAULT_TOP_WINDOWS) -> list[dict[str, Any]]:
    return rank_cooking_windows()[:top]


def _hour_reward_signals() -> dict[int, tuple[float, float]]:
    """Per hour-of-day (green_share, grid_benefit), both in [0, 1].

    The rules-baseline analogue of the model's green-probability and grid-benefit
    factors, computed from the hourly telemetry aggregates.
    """
    aggregates = _hourly_aggregates()
    if not aggregates:
        return {}
    pv_by_hour = {hour: bucket["pv_power_w_sum"] / bucket["samples"]
                  for hour, bucket in aggregates.items()}
    load_by_hour = {hour: bucket["load_w_sum"] / bucket["samples"]
                    for hour, bucket in aggregates.items()}
    peak_pv = max(pv_by_hour.values()) or 1.0
    peak_load = max(load_by_hour.values()) or 1.0

    signals: dict[int, tuple[float, float]] = {}
    for hour, bucket in aggregates.items():
        green_share = bucket["green"] / bucket["samples"]
        soc_norm = (bucket["battery_soc_sum"] / bucket["samples"]) / MAX_BATTERY_SOC_PERCENT
        benefit = (
            0.5 * (pv_by_hour[hour] / peak_pv)
            + 0.3 * soc_norm
            + 0.2 * (1.0 - load_by_hour[hour] / peak_load)
        )
        signals[hour] = (green_share, min(max(benefit, 0.0), 1.0))
    return signals


def estimate_credit_gain(slot_color: str, expected_kwh: float, hour: int) -> dict[str, Any]:
    """Fallback smart reward when the ML service is down; 0 for non-green windows.

    Mirrors the model's ``BASE x confidence x grid_benefit`` shape using the
    hourly green-share (confidence proxy) and grid-benefit aggregates. Capped at
    1.0 per session; whole credits come from accumulation. ``expected_kwh`` is
    kept for signature stability.
    """
    if slot_color != SLOT_GREEN:
        return {
            "suggested_credit_gain": 0.0,
            "credit_gain_basis": f"{slot_color} window earns no credit",
            "model_version": CREDIT_MODEL_VERSION,
        }

    green_share, grid_benefit = _hour_reward_signals().get(hour, (0.5, 0.5))
    suggested = round(min(BASE_REWARD * green_share * grid_benefit, MAX_SESSION_CREDIT), 3)
    return {
        "suggested_credit_gain": suggested,
        "credit_gain_basis": (
            f"rules smart: green_share={green_share:.2f} x grid_benefit={grid_benefit:.2f}"
        ),
        "model_version": CREDIT_MODEL_VERSION,
    }


def assess_cooking_time(hour: int, planned_duration_minutes: float | None = None,
                        account_id: str | None = None) -> dict[str, Any]:
    """Assess a user-chosen cooking hour and return slot, energy, and credit gain.

    Preference order: live per-account model (``ml/api``) -> grid-level model
    (live community / cached export, already applied in ``rank_cooking_windows``)
    -> rules baseline.
    """
    ranked = rank_cooking_windows()
    by_hour = {window["hour_eat"]: window for window in ranked}
    window = by_hour.get(hour)

    if window is None:
        slot_color = SLOT_RED
        expected_kwh = FALLBACK_SESSION_KWH
        reason = "No grid history for this hour; treated as an off-peak window."
        credit = estimate_credit_gain(slot_color, expected_kwh, hour)
    else:
        slot_color = window["slot_color"]
        expected_kwh = window["expected_kwh"] or FALLBACK_SESSION_KWH
        reason = window["reason"]
        credit = {
            "suggested_credit_gain": window["suggested_credit_gain"],
            "credit_gain_basis": window["credit_gain_basis"],
            "model_version": window["model_version"],
        }

    # Most specific tier: a live forward pass for this exact account.
    if account_id is not None:
        live = ml_client.plan(account_id, hour, planned_duration_minutes=planned_duration_minutes)
        if live is not None:
            slot_color = live["slot_color"]
            expected_kwh = live["expected_kwh"]
            reason = f"Live model prediction ({live['model_version']}) for {account_id}."
            credit = {
                "suggested_credit_gain": live["suggested_credit_gain"],
                "credit_gain_basis": live["credit_gain_basis"],
                "model_version": live["model_version"],
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
