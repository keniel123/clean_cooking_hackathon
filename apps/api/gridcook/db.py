"""File-backed SQLite store for the Oloika dataset plus live runtime state.

The documented source of truth is the CSV/JSON files in ``data/synthetic``
(see ``docs/oloika_data_schema_and_prediction_notes.md``). On first startup the
API seeds those read-only reference tables into a file-backed SQLite database
(``data/runtime/gridcook.db``). Runtime tables (bookings, live cooking
sessions, and the continual-learning counter) then persist across restarts so
real usage survives and can be funneled into the ML training loop.
"""

from __future__ import annotations

import csv
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

INTEGER = "INTEGER"
REAL = "REAL"

# apps/api/gridcook/db.py -> repo root is three directories up.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data" / "synthetic"
_DEFAULT_DB_PATH = _REPO_ROOT / "data" / "runtime" / "gridcook.db"

MONTH = "2025-06"

# Table name -> (csv filename, numeric column type overrides).
# Columns not listed default to TEXT. Only numeric columns need declaring so
# that ordering and range comparisons behave numerically instead of textually.
_TABLE_SOURCES: dict[str, tuple[str, dict[str, str]]] = {
    "minigrid_accounts": ("oloika_minigrid_accounts.csv", {}),
    "cooker_assets": ("oloika_cooker_assets.csv", {}),
    "people": ("oloika_people.csv", {}),
    "households": (
        "oloika_households.csv",
        {
            "occupants": INTEGER,
            "children_count": INTEGER,
            "meal_count_per_day": INTEGER,
            "current_fuel_cost_kes_week": REAL,
            "fuel_collection_minutes_week": REAL,
            "time_spent_cooking_minutes_day": REAL,
            "estimated_other_grid_kwh_week": REAL,
            "clean_cooking_readiness_score": REAL,
            "shiftable_cooking_score": REAL,
        },
    ),
    "commercial_profiles": (
        "oloika_commercial_profiles.csv",
        {
            "customers_avg_week": INTEGER,
            "fuel_cost_kes_week": REAL,
            "cooking_hours_day": REAL,
            "estimated_cooking_kwh_week": REAL,
            "clean_cooking_readiness_score": REAL,
            "daytime_shift_potential": REAL,
        },
    ),
    "grid_hourly": (
        "oloika_grid_hourly_june_2025.csv",
        {
            "hour_eat": INTEGER,
            "battery_soc_percent": REAL,
            "battery_power_w": REAL,
            "pv_dc_power_w": REAL,
            "pv_ac_power_w": REAL,
            "fronius_pv_power_w": REAL,
            "ac_load_w": REAL,
            "fronius_consumption_w": REAL,
            "voltage_avg_v": REAL,
            "system_alarm_count": INTEGER,
        },
    ),
    "cooking_sessions": (
        "oloika_cooking_sessions_june_2025.csv",
        {
            "start_hour_eat": INTEGER,
            "duration_minutes": REAL,
            "kwh": REAL,
            "avg_w": REAL,
            "peak_w": INTEGER,
            "shifted_daytime": INTEGER,
        },
    ),
    "cooker_utilization_daily": (
        "oloika_cooker_utilization_daily_june_2025.csv",
        {
            "active_minutes": REAL,
            "available_minutes": REAL,
            "utilization_percent": REAL,
            "kwh": REAL,
            "session_count": INTEGER,
            "observed_sessions": INTEGER,
            "synthetic_sessions": INTEGER,
            "green_sessions": INTEGER,
            "orange_sessions": INTEGER,
            "red_sessions": INTEGER,
            "peak_concurrent_cookers": INTEGER,
        },
    ),
    "account_daily_behavior": (
        "oloika_account_daily_behavior_june_2025.csv",
        {
            "sessions": INTEGER,
            "kwh": REAL,
            "green_window_share": REAL,
            "red_window_sessions": INTEGER,
            "shifted_daytime_sessions": INTEGER,
            "credits_earned": INTEGER,
            "credits_spent": INTEGER,
            "fuel_stacking_risk_flag": INTEGER,
            "green_sessions": INTEGER,
            "orange_sessions": INTEGER,
            "red_sessions": INTEGER,
        },
    ),
    "billing_ledger": (
        "oloika_billing_ledger_june_2025.csv",
        {
            "credits_delta": INTEGER,
            "cash_kes": INTEGER,
            "balance_after": INTEGER,
        },
    ),
    "credit_balances": (
        "oloika_credit_balances_june_2025.csv",
        {
            "ending_balance_credits": INTEGER,
            "total_top_up_credits": INTEGER,
            "total_reward_credits": INTEGER,
            "total_spent_credits": INTEGER,
            "cash_paid_kes": INTEGER,
        },
    ),
    "leaderboard": (
        "oloika_leaderboard_june_2025.csv",
        {
            "rank": INTEGER,
            "sessions": INTEGER,
            "kwh": REAL,
            "green_sessions": INTEGER,
            "orange_sessions": INTEGER,
            "red_sessions": INTEGER,
            "green_window_share": REAL,
            "shifted_daytime_sessions": INTEGER,
            "credits_earned": INTEGER,
            "credits_spent": INTEGER,
            "ending_balance_credits": INTEGER,
            "cash_paid_kes": INTEGER,
            "fuel_stacking_risk_days": INTEGER,
            "score": INTEGER,
        },
    ),
}

# Standalone JSON summaries surfaced through the stats endpoints.
_JSON_SOURCES: dict[str, str] = {
    "monthly_summary": "oloika_monthly_dataset_summary.json",
    "persona_summary": "oloika_persona_summary.json",
    "schema": "oloika_dataset_schema.json",
    "generation_assumptions": "oloika_generation_assumptions.json",
}

# Guards the shared in-memory connection: sync FastAPI endpoints run in a
# thread pool, and a single SQLite connection is not safe for concurrent use.
_lock = threading.Lock()
_connection: sqlite3.Connection | None = None
_json_cache: dict[str, Any] = {}


def _data_dir() -> Path:
    override = os.environ.get("GRIDCOOK_DATA_DIR")
    return Path(override) if override else _DEFAULT_DATA_DIR


def _coerce(value: str, sqlite_type: str | None) -> Any:
    if value == "" or value is None:
        return None
    if sqlite_type == INTEGER:
        return int(float(value))
    if sqlite_type == REAL:
        return float(value)
    return value


def _load_table(connection: sqlite3.Connection, table: str, filename: str,
                numeric_columns: dict[str, str]) -> None:
    path = _data_dir() / filename
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        column_defs = ", ".join(
            f'"{name}" {numeric_columns.get(name, "TEXT")}' for name in header
        )
        connection.execute(f'CREATE TABLE "{table}" ({column_defs})')
        placeholders = ", ".join("?" for _ in header)
        insert_sql = f'INSERT INTO "{table}" VALUES ({placeholders})'
        rows = (
            [_coerce(value, numeric_columns.get(name)) for name, value in zip(header, record)]
            for record in reader
        )
        connection.executemany(insert_sql, rows)


# Runtime tables persist across restarts and are populated by write endpoints:
# ``cooking_plans`` are bookings (committed shared-grid load), ``cooking_sessions_live``
# are actual usage that funnels into ML training, and ``train_state`` tracks how
# many sessions have accrued since the last continual-learning update.
_RUNTIME_TABLES = (
    """
    CREATE TABLE IF NOT EXISTS cooking_plans (
        plan_id TEXT PRIMARY KEY,
        account_id TEXT NOT NULL,
        cooker_id TEXT,
        date TEXT NOT NULL,
        start_hour_eat INTEGER NOT NULL,
        planned_duration_minutes REAL,
        slot_color TEXT NOT NULL,
        expected_kwh REAL NOT NULL,
        suggested_credit_gain REAL NOT NULL,
        credit_gain_basis TEXT NOT NULL,
        model_version TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS cooking_sessions_live (
        session_id TEXT PRIMARY KEY,
        account_id TEXT NOT NULL,
        cooker_id TEXT,
        date TEXT NOT NULL,
        start_hour_eat INTEGER NOT NULL,
        duration_minutes REAL,
        kwh REAL NOT NULL,
        slot_color TEXT NOT NULL,
        suggested_credit_gain REAL NOT NULL,
        credit_gain_basis TEXT NOT NULL,
        model_version TEXT NOT NULL,
        shifted_daytime INTEGER NOT NULL,
        source TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS credit_wallet (
        account_id TEXT PRIMARY KEY,
        accumulated_credit REAL NOT NULL,
        credits_awarded INTEGER NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS train_state (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        sessions_since_train INTEGER NOT NULL,
        last_trained_version TEXT,
        last_trained_at TEXT
    )
    """,
)


def _db_path() -> Path:
    override = os.environ.get("GRIDCOOK_DB_PATH")
    return Path(override) if override else _DEFAULT_DB_PATH


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", [name]
    ).fetchone()
    return row is not None


def _build_connection() -> sqlite3.Connection:
    path = _db_path()
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), check_same_thread=False)
    connection.row_factory = sqlite3.Row

    # Reference tables are seeded from CSV only once (first run / fresh file).
    for table, (filename, numeric_columns) in _TABLE_SOURCES.items():
        if not _table_exists(connection, table):
            _load_table(connection, table, filename, numeric_columns)

    for statement in _RUNTIME_TABLES:
        connection.execute(statement)
    connection.execute(
        "INSERT OR IGNORE INTO train_state (id, sessions_since_train, "
        "last_trained_version, last_trained_at) VALUES (1, 0, NULL, NULL)"
    )
    connection.commit()
    return connection


def get_connection() -> sqlite3.Connection:
    """Return the shared file-backed connection, seeding the dataset on first use."""
    global _connection
    if _connection is None:
        _connection = _build_connection()
    return _connection


def get_json(name: str) -> Any:
    """Return a parsed JSON summary file, cached after first read."""
    if name not in _json_cache:
        path = _data_dir() / _JSON_SOURCES[name]
        _json_cache[name] = json.loads(path.read_text(encoding="utf-8"))
    return _json_cache[name]


def _build_where(filters: dict[str, Any]) -> tuple[str, list[Any]]:
    active = {column: value for column, value in filters.items() if value is not None}
    if not active:
        return "", []
    clause = " WHERE " + " AND ".join(f'"{column}" = ?' for column in active)
    return clause, list(active.values())


def query(sql: str, params: list[Any] | tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    """Run an arbitrary read query and return rows as dictionaries."""
    with _lock:
        cursor = get_connection().execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]


def insert_row(table: str, row: dict[str, Any]) -> None:
    """Insert a single row into a known table (used by write endpoints)."""
    columns = list(row)
    column_sql = ", ".join(f'"{column}"' for column in columns)
    placeholders = ", ".join("?" for _ in columns)
    with _lock:
        connection = get_connection()
        connection.execute(
            f'INSERT INTO "{table}" ({column_sql}) VALUES ({placeholders})',
            [row[column] for column in columns],
        )
        connection.commit()


def update_value(table: str, key_column: str, key_value: Any,
                 set_column: str, set_value: Any) -> int:
    """Update a single column for rows matching a key; returns affected row count."""
    with _lock:
        connection = get_connection()
        cursor = connection.execute(
            f'UPDATE "{table}" SET "{set_column}" = ? WHERE "{key_column}" = ?',
            [set_value, key_value],
        )
        connection.commit()
        return cursor.rowcount


def select_rows(table: str, filters: dict[str, Any] | None = None,
                order_by: str | None = None, limit: int | None = None,
                offset: int = 0) -> list[dict[str, Any]]:
    """Select rows from a known table with equality filters and pagination.

    Table, column, and order-by names are always supplied by API code (never by
    raw client input), so they are safe to interpolate; values are parameterised.
    """
    where_clause, params = _build_where(filters or {})
    sql = f'SELECT * FROM "{table}"{where_clause}'
    if order_by:
        sql += f" ORDER BY {order_by}"
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params = params + [limit, offset]
    return query(sql, params)


def count_rows(table: str, filters: dict[str, Any] | None = None) -> int:
    """Count rows in a known table with the same equality filters as ``select_rows``."""
    where_clause, params = _build_where(filters or {})
    result = query(f'SELECT COUNT(*) AS total FROM "{table}"{where_clause}', params)
    return int(result[0]["total"])


def award_session_credit(account_id: str, amount: float) -> dict[str, Any]:
    """Add a fractional session credit to an account's wallet.

    Credits accumulate; a whole credit is only "awarded" when the running total
    crosses an integer boundary. Returns the updated wallet state including how
    many whole credits (if any) this session realized.
    """
    now = datetime.now(timezone.utc).isoformat()
    with _lock:
        connection = get_connection()
        row = connection.execute(
            "SELECT accumulated_credit, credits_awarded FROM credit_wallet WHERE account_id = ?",
            [account_id],
        ).fetchone()
        previous_total = float(row["accumulated_credit"]) if row else 0.0
        previous_awarded = int(row["credits_awarded"]) if row else 0

        new_total = previous_total + float(amount)
        new_awarded = int(new_total)  # floor: whole credits realized so far
        credited_now = new_awarded - previous_awarded

        if row:
            connection.execute(
                "UPDATE credit_wallet SET accumulated_credit = ?, credits_awarded = ?, "
                "updated_at = ? WHERE account_id = ?",
                [new_total, new_awarded, now, account_id],
            )
        else:
            connection.execute(
                "INSERT INTO credit_wallet (account_id, accumulated_credit, credits_awarded, "
                "updated_at) VALUES (?, ?, ?, ?)",
                [account_id, new_total, new_awarded, now],
            )
        connection.commit()

    return {
        "account_id": account_id,
        "session_credit": round(float(amount), 3),
        "accumulated_credit": round(new_total, 3),
        "credits_awarded": new_awarded,
        "credited_this_session": credited_now,
        "progress_to_next_credit": round(new_total - new_awarded, 3),
        "updated_at": now,
    }


def get_train_state() -> dict[str, Any]:
    """Return the single continual-learning bookkeeping row."""
    return query("SELECT * FROM train_state WHERE id = 1")[0]


def bump_sessions_since_train(delta: int = 1) -> int:
    """Increment the session counter and return the new value."""
    with _lock:
        connection = get_connection()
        connection.execute(
            "UPDATE train_state SET sessions_since_train = sessions_since_train + ? WHERE id = 1",
            [delta],
        )
        connection.commit()
        row = connection.execute(
            "SELECT sessions_since_train FROM train_state WHERE id = 1"
        ).fetchone()
        return int(row[0])


def reset_sessions_since_train(trained_version: str | None = None) -> None:
    """Zero the counter and record the last-trained version/time."""
    with _lock:
        connection = get_connection()
        connection.execute(
            "UPDATE train_state SET sessions_since_train = 0, "
            "last_trained_version = COALESCE(?, last_trained_version), "
            "last_trained_at = ? WHERE id = 1",
            [trained_version, datetime.now(timezone.utc).isoformat()],
        )
        connection.commit()
