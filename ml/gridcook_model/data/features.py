"""Load the Oloika dataset and build model-ready feature frames.

Source of truth is ``data/synthetic`` (the same CSVs the API loads). This module
turns those raw tables into numeric feature matrices for the four models:

- Grid/solar forecaster (F): rolling sequences of hourly grid features.
- Grid-risk classifier (R): per-hour grid features -> slot color.
- Cooking-demand forecaster (D): per-hour features -> sessions and kWh.
- Recommender/credit model (C): account + persona + grid-hour features -> slot + kWh.
"""

from __future__ import annotations

import math
import os
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

# ml/gridcook_model/data/features.py -> repo root is three parents up.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data" / "synthetic"

SLOT_COLORS = ["green", "orange", "red"]
SLOT_TO_INDEX = {color: index for index, color in enumerate(SLOT_COLORS)}
INDEX_TO_SLOT = {index: color for color, index in SLOT_TO_INDEX.items()}

GRID_FEATURE_COLUMNS = [
    "hour_sin",
    "hour_cos",
    "pv_power_w",
    "battery_soc_percent",
    "ac_load_w",
    "voltage_avg_v",
    "system_alarm_count",
]
FORECAST_TARGET_COLUMNS = ["pv_power_w", "battery_soc_percent", "ac_load_w"]

_PV_SOURCE_COLUMNS = ["fronius_pv_power_w", "pv_ac_power_w", "pv_dc_power_w"]


_SESSIONS_FILE = "oloika_cooking_sessions_june_2025.csv"


def data_dir() -> Path:
    override = os.environ.get("GRIDCOOK_DATA_DIR")
    return Path(override) if override else _DEFAULT_DATA_DIR


def load_csv(filename: str) -> pd.DataFrame:
    return pd.read_csv(data_dir() / filename)


def live_sessions_path() -> Path:
    override = os.environ.get("GRIDCOOK_LIVE_SESSIONS")
    return Path(override) if override else _REPO_ROOT / "data" / "runtime" / "live_sessions.csv"


def load_live_sessions() -> pd.DataFrame:
    """Sessions recorded live by the API since the last training run (may be empty)."""
    path = live_sessions_path()
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def load_sessions() -> pd.DataFrame:
    """Historical June sessions plus any live sessions funneled from the API.

    This is the bridge that lets the recommender learn from real community
    usage: rows the API appended to ``data/runtime/live_sessions.csv`` share the
    same schema, so they concatenate directly onto the shipped history.
    """
    base = load_csv(_SESSIONS_FILE)
    live = load_live_sessions()
    if live.empty:
        return base
    return pd.concat([base, live[base.columns.intersection(live.columns)]], ignore_index=True)


def _add_cyclical_hour(frame: pd.DataFrame, hour_column: str = "hour_eat") -> pd.DataFrame:
    radians = frame[hour_column].astype(float) * (2.0 * math.pi / 24.0)
    frame["hour_sin"] = np.sin(radians)
    frame["hour_cos"] = np.cos(radians)
    return frame


@lru_cache(maxsize=1)
def build_grid_frame() -> pd.DataFrame:
    """Return hourly grid rows with engineered features and an integer slot label.

    Cached: the historical grid CSV is static for the life of the process, so this
    (and the account table below) are built once. This is what keeps live
    inference and in-process retrains fast - callers treat the result as read-only.
    """
    frame = load_csv("oloika_grid_hourly_june_2025.csv").copy()
    frame["pv_power_w"] = frame[_PV_SOURCE_COLUMNS].max(axis=1, skipna=True)
    frame["pv_power_w"] = frame["pv_power_w"].fillna(0.0)
    frame["battery_soc_percent"] = frame["battery_soc_percent"].fillna(
        frame["battery_soc_percent"].median()
    )
    frame["ac_load_w"] = frame["ac_load_w"].fillna(frame["ac_load_w"].median())
    frame["voltage_avg_v"] = frame["voltage_avg_v"].fillna(frame["voltage_avg_v"].median())
    frame["system_alarm_count"] = frame["system_alarm_count"].fillna(0).astype(float)
    frame = _add_cyclical_hour(frame)
    frame["slot_index"] = frame["slot_color"].map(SLOT_TO_INDEX).astype(int)
    frame = frame.sort_values("timestamp_hour").reset_index(drop=True)
    return frame


@lru_cache(maxsize=1)
def grid_benefit_by_hour() -> dict[int, float]:
    """Per hour-of-day 'how much cooking here helps the grid' score in [0, 1].

    Rewards high solar and a healthy battery, penalizes high community load, so a
    session shifted into a solar-rich, low-stress hour scores near 1 and a
    stressed evening hour scores near 0. Used by the smart reward model.
    """
    grid = build_grid_frame()
    hourly = grid.groupby("hour_eat")[["pv_power_w", "battery_soc_percent", "ac_load_w"]].mean()
    pv_peak = hourly["pv_power_w"].max() or 1.0
    load_peak = hourly["ac_load_w"].max() or 1.0

    benefit: dict[int, float] = {}
    for hour, row in hourly.iterrows():
        pv_norm = row["pv_power_w"] / pv_peak
        soc_norm = row["battery_soc_percent"] / 100.0
        load_norm = row["ac_load_w"] / load_peak
        score = 0.5 * pv_norm + 0.3 * soc_norm + 0.2 * (1.0 - load_norm)
        benefit[int(hour)] = float(min(max(score, 0.0), 1.0))
    return benefit


def build_grid_sequences(lookback: int, horizon: int) -> tuple[np.ndarray, np.ndarray]:
    """Build (X, Y) rolling windows for the forecaster.

    X: (samples, lookback, len(GRID_FEATURE_COLUMNS))
    Y: (samples, horizon, len(FORECAST_TARGET_COLUMNS))
    """
    frame = build_grid_frame()
    features = frame[GRID_FEATURE_COLUMNS].to_numpy(dtype=np.float32)
    targets = frame[FORECAST_TARGET_COLUMNS].to_numpy(dtype=np.float32)

    inputs: list[np.ndarray] = []
    outputs: list[np.ndarray] = []
    last_start = len(frame) - lookback - horizon
    for start in range(last_start + 1):
        inputs.append(features[start:start + lookback])
        outputs.append(targets[start + lookback:start + lookback + horizon])
    if not inputs:
        return np.empty((0, lookback, len(GRID_FEATURE_COLUMNS)), dtype=np.float32), \
            np.empty((0, horizon, len(FORECAST_TARGET_COLUMNS)), dtype=np.float32)
    return np.stack(inputs), np.stack(outputs)


def build_risk_dataset() -> tuple[np.ndarray, np.ndarray, pd.Series]:
    """Per-hour grid features -> slot index. Returns (X, y, dates)."""
    frame = build_grid_frame()
    features = frame[GRID_FEATURE_COLUMNS].to_numpy(dtype=np.float32)
    labels = frame["slot_index"].to_numpy(dtype=np.int64)
    return features, labels, frame["date"]


def build_demand_dataset() -> tuple[np.ndarray, np.ndarray, pd.Series, np.ndarray]:
    """Per (date, hour) features -> [sessions, kwh]. Returns (X, y, dates, hours)."""
    grid = build_grid_frame()
    sessions = load_sessions()
    grouped = (
        sessions.groupby(["date", "start_hour_eat"])
        .agg(sessions=("session_id", "count"), kwh=("kwh", "sum"))
        .reset_index()
        .rename(columns={"start_hour_eat": "hour_eat"})
    )
    merged = grid.merge(grouped, on=["date", "hour_eat"], how="left")
    merged["sessions"] = merged["sessions"].fillna(0.0)
    merged["kwh"] = merged["kwh"].fillna(0.0)

    features = merged[GRID_FEATURE_COLUMNS].to_numpy(dtype=np.float32)
    targets = merged[["sessions", "kwh"]].to_numpy(dtype=np.float32)
    hours = merged["hour_eat"].to_numpy(dtype=np.int64)
    return features, targets, merged["date"], hours


# --------------------------------------------------------------------------- #
# Account + persona features for the recommender
# --------------------------------------------------------------------------- #

ACCOUNT_BEHAVIOR_COLUMNS = [
    "sessions",
    "kwh",
    "green_window_share",
    "red_window_sessions",
    "shifted_daytime_sessions",
    "credits_earned",
    "credits_spent",
    "fuel_stacking_risk_flag",
]


@lru_cache(maxsize=1)
def grid_hour_means() -> pd.DataFrame:
    """Mean grid features per hour-of-day (cached; drives inference feature rows)."""
    return build_grid_frame().groupby("hour_eat")[GRID_FEATURE_COLUMNS].mean()


@lru_cache(maxsize=1)
def build_account_feature_table() -> tuple[pd.DataFrame, list[str]]:
    """One row per account: mean daily behavior + persona + type. Indexed by account_id.

    Cached for the process lifetime (see ``build_grid_frame``); returned frame is
    treated as read-only by callers.
    """
    accounts = load_csv("oloika_minigrid_accounts.csv")
    behavior = load_csv("oloika_account_daily_behavior_june_2025.csv")
    households = load_csv("oloika_households.csv")
    commercial = load_csv("oloika_commercial_profiles.csv")

    behavior_mean = (
        behavior.groupby("account_id")[ACCOUNT_BEHAVIOR_COLUMNS].mean().reset_index()
    )

    persona = pd.DataFrame({"entity_id": accounts["entity_id"].unique()})
    hh = households[["household_id", "clean_cooking_readiness_score", "shiftable_cooking_score"]]
    hh = hh.rename(columns={"household_id": "entity_id"})
    biz = commercial[["business_id", "clean_cooking_readiness_score", "daytime_shift_potential"]]
    biz = biz.rename(columns={
        "business_id": "entity_id",
        "daytime_shift_potential": "shiftable_cooking_score",
    })
    persona_features = pd.concat([hh, biz], ignore_index=True)

    table = accounts.merge(behavior_mean, on="account_id", how="left")
    table = table.merge(persona_features, on="entity_id", how="left")
    table["is_commercial"] = (table["account_type"] == "commercial").astype(float)
    for column in ACCOUNT_BEHAVIOR_COLUMNS + [
        "clean_cooking_readiness_score", "shiftable_cooking_score"
    ]:
        table[column] = table[column].fillna(table[column].median())

    feature_columns = ACCOUNT_BEHAVIOR_COLUMNS + [
        "clean_cooking_readiness_score", "shiftable_cooking_score", "is_commercial",
    ]
    table = table.set_index("account_id")
    return table, feature_columns


def build_recommender_dataset() -> tuple[np.ndarray, np.ndarray, np.ndarray, pd.Series, list[str]]:
    """Session-level rows for the recommender.

    Each cooking session yields: account features + grid-hour features for that
    session's hour -> (slot index, kwh). Returns (X, y_slot, y_kwh, dates, columns).
    """
    account_table, account_columns = build_account_feature_table()
    grid_hour = grid_hour_means()

    sessions = load_sessions().copy()
    sessions = sessions[sessions["account_id"].isin(account_table.index)]

    account_matrix = account_table.loc[sessions["account_id"], account_columns].to_numpy(np.float32)
    grid_matrix = grid_hour.loc[sessions["start_hour_eat"], GRID_FEATURE_COLUMNS].to_numpy(np.float32)
    features = np.concatenate([account_matrix, grid_matrix], axis=1)

    slot = sessions["slot_color"].map(SLOT_TO_INDEX).to_numpy(np.int64)
    kwh = sessions["kwh"].to_numpy(np.float32).reshape(-1, 1)
    columns = list(account_columns) + list(GRID_FEATURE_COLUMNS)
    return features, slot, kwh, sessions["date"], columns


def account_grid_feature_row(account_id: str, hour: int) -> tuple[np.ndarray, list[str]] | None:
    """Feature row for one (account, hour), matching build_recommender_dataset columns.

    Used at inference time. Returns None if the account is unknown.
    """
    account_table, account_columns = build_account_feature_table()
    if account_id not in account_table.index:
        return None
    grid_hour = grid_hour_means()
    hour = int(hour) if int(hour) in grid_hour.index else int(grid_hour.index[0])

    account_vector = account_table.loc[account_id, account_columns].to_numpy(np.float32)
    grid_vector = grid_hour.loc[hour, GRID_FEATURE_COLUMNS].to_numpy(np.float32)
    row = np.concatenate([account_vector, grid_vector]).astype(np.float32)
    columns = list(account_columns) + list(GRID_FEATURE_COLUMNS)
    return row, columns
