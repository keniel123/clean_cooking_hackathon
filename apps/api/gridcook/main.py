"""GridCook Oloika REST API.

Serves the documented Oloika June 2025 synthetic dataset over RESTful,
resource-oriented endpoints, plus a rules-first "best time to cook"
recommendation engine.

Run locally:

    uvicorn gridcook.main:app --reload --port 8000

Interactive docs are then available at http://127.0.0.1:8000/docs
"""

from __future__ import annotations

import csv
import os
import time
import uuid
from datetime import date as date_cls
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import capacity, db, ml_client, scoring

# Ezra's atomic write path (data/oloika_write.py). It lives outside the API
# package; make it importable via GRIDCOOK_DBTOOLS (dir holding oloika_write.py,
# /app/dbtools in the container). Writes require persistent DB mode
# (GRIDCOOK_DB_PATH set); otherwise the write endpoints return 503.
import os as _os, sys as _sys
_dbtools = _os.environ.get("GRIDCOOK_DBTOOLS")
if _dbtools and _dbtools not in _sys.path:
    _sys.path.insert(0, _dbtools)
try:
    import oloika_write  # type: ignore
except Exception:  # pragma: no cover
    oloika_write = None

API_PREFIX = "/api/v1"
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 500

PLAN_STATUS_PLANNED = "planned"
PLAN_STATUS_CONFIRMED = "confirmed"
PLAN_STATUS_CANCELLED = "cancelled"

# Continual learning: retrain after this many recorded live sessions.
RETRAIN_EVERY = int(os.environ.get("GRIDCOOK_RETRAIN_EVERY", "20"))
# The retrain itself runs asynchronously on ml/api; these bound the off-request
# poll that records the promoted version for bookkeeping.
RETRAIN_POLL_TIMEOUT_SECONDS = float(os.environ.get("GRIDCOOK_RETRAIN_POLL_TIMEOUT", "300"))
RETRAIN_POLL_INTERVAL_SECONDS = 3.0
DAYTIME_START_HOUR = scoring.DAYTIME_START_HOUR
DAYTIME_END_HOUR = scoring.DAYTIME_END_HOUR
DEFAULT_SESSION_KWH = scoring.FALLBACK_SESSION_KWH

# apps/api/gridcook/main.py -> repo root is three parents up.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_LIVE_SESSIONS_PATH = Path(
    os.environ.get("GRIDCOOK_LIVE_SESSIONS")
    or (_REPO_ROOT / "data" / "runtime" / "live_sessions.csv")
)

# Schema mirrors data/synthetic/oloika_cooking_sessions_june_2025.csv so the ML
# trainer can concatenate live rows with history without any remapping.
_LIVE_SESSION_COLUMNS = [
    "session_id", "account_id", "entity_id", "account_type", "cooker_id", "plug",
    "observed_group", "source", "start_at", "end_at", "date", "start_hour_eat",
    "duration_minutes", "kwh", "avg_w", "peak_w", "slot_color", "shifted_daytime",
]


def _today() -> str:
    return date_cls.today().isoformat()


def _capacity_aware_assessment(account_id: str, plan_date: str, hour: int,
                               duration_minutes: float | None) -> dict[str, Any]:
    """Score a chosen hour with the model, then overlay live shared-grid capacity."""
    assessment = scoring.assess_cooking_time(hour, duration_minutes, account_id=account_id)
    window = {
        "hour_eat": hour,
        "slot_color": assessment["slot_color"],
        "expected_kwh": assessment["expected_kwh"],
        "suggested_credit_gain": assessment["suggested_credit_gain"],
    }
    adjusted = capacity.adjust_windows([window], plan_date)[0]
    assessment["slot_color"] = adjusted["slot_color"]
    assessment["suggested_credit_gain"] = adjusted["suggested_credit_gain"]
    assessment["capacity_note"] = adjusted.get("capacity_note")
    assessment["capacity_utilisation"] = adjusted.get("capacity_utilisation")
    assessment["headroom_kwh"] = adjusted.get("headroom_kwh")
    assessment["committed_cookers"] = adjusted.get("committed_cookers")
    return assessment


def _run_retrain_and_record() -> None:
    """Kick off the async retrain on ml/api, then (off the request path) wait for
    it to finish and record the promoted model version for bookkeeping."""
    if ml_client.trigger_continual_update() is None:
        return
    deadline = time.monotonic() + RETRAIN_POLL_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        status = ml_client.retrain_status()
        if status is None:
            return
        if not status.get("running"):
            db.reset_sessions_since_train(status.get("model_version"))
            return
        time.sleep(RETRAIN_POLL_INTERVAL_SECONDS)


def _append_live_session_csv(row: dict[str, Any]) -> None:
    """Append one session to the ML-readable live sessions CSV (create header once)."""
    _LIVE_SESSIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_header = not _LIVE_SESSIONS_PATH.exists()
    with _LIVE_SESSIONS_PATH.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=_LIVE_SESSION_COLUMNS)
        if write_header:
            writer.writeheader()
        writer.writerow({column: row.get(column, "") for column in _LIVE_SESSION_COLUMNS})

app = FastAPI(
    title="GridCook Oloika API",
    version="1.0.0",
    description="RESTful access to the Oloika June 2025 clean-cooking dataset.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _paginated(table: str, filters: dict[str, Any], order_by: str,
               limit: int, offset: int) -> dict[str, Any]:
    """Standard list envelope: total count plus the requested page of rows."""
    total = db.count_rows(table, filters)
    rows = db.select_rows(table, filters, order_by=order_by, limit=limit, offset=offset)
    return {"count": total, "limit": limit, "offset": offset, "results": rows}


def _get_one(table: str, key_column: str, key_value: Any, label: str) -> dict[str, Any]:
    rows = db.select_rows(table, {key_column: key_value}, limit=1)
    if not rows:
        raise HTTPException(status_code=404, detail=f"{label} '{key_value}' not found")
    return rows[0]


class CookingPlanRequest(BaseModel):
    """A user's chosen cooking time to be scored for reward credits."""

    account_id: str = Field(..., examples=["HH-0007"])
    date: str = Field(..., description="Calendar date, YYYY-MM-DD", examples=["2025-06-15"])
    start_hour_eat: int = Field(..., ge=0, le=23, description="Chosen start hour (EAT)")
    cooker_id: str | None = Field(None, description="Optional specific cooker")
    planned_duration_minutes: float | None = Field(None, gt=0)


class PlanStatusUpdate(BaseModel):
    status: str = Field(..., examples=[PLAN_STATUS_CONFIRMED, PLAN_STATUS_CANCELLED])


class SessionRecordRequest(BaseModel):
    """An actual cooking session a user ran on the shared grid."""

    account_id: str = Field(..., examples=["HH-0007"])
    date: str = Field(..., description="Calendar date, YYYY-MM-DD", examples=["2025-06-15"])
    start_hour_eat: int = Field(..., ge=0, le=23, description="Hour the session started (EAT)")
    duration_minutes: float | None = Field(None, gt=0)
    cooker_id: str | None = Field(None, description="Optional specific cooker")
    kwh: float | None = Field(None, gt=0, description="Measured energy; estimated if omitted")


# --------------------------------------------------------------------------- #
# Health and stats
# --------------------------------------------------------------------------- #

@app.get("/health", tags=["meta"])
def health() -> dict[str, Any]:
    return {"status": "ok", "month": db.MONTH, "accounts": db.count_rows("minigrid_accounts")}


@app.get(f"{API_PREFIX}/stats/summary", tags=["stats"])
def dataset_summary() -> dict[str, Any]:
    return db.get_json("monthly_summary")


@app.get(f"{API_PREFIX}/stats/personas", tags=["stats"])
def persona_summary() -> dict[str, Any]:
    return db.get_json("persona_summary")


@app.get(f"{API_PREFIX}/stats/schema", tags=["stats"])
def dataset_schema() -> dict[str, Any]:
    return db.get_json("schema")


# --------------------------------------------------------------------------- #
# Mini-grid accounts
# --------------------------------------------------------------------------- #

@app.get(f"{API_PREFIX}/accounts", tags=["accounts"])
def list_accounts(
    account_type: str | None = Query(None, description="household or commercial"),
    community_id: str | None = None,
    meter_status: str | None = None,
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    filters = {
        "account_type": account_type,
        "community_id": community_id,
        "meter_status": meter_status,
    }
    return _paginated("minigrid_accounts", filters, "account_id", limit, offset)


@app.get(f"{API_PREFIX}/accounts/{{account_id}}", tags=["accounts"])
def get_account(account_id: str) -> dict[str, Any]:
    return _get_one("minigrid_accounts", "account_id", account_id, "Account")


@app.get(f"{API_PREFIX}/customers/{{identifier}}", tags=["accounts"])
def find_customer(identifier: str) -> dict[str, Any]:
    """Find a customer by account_id OR phone number (SMS / ops lookup) and
    return identity plus a usage summary: recent consumption, total charged, and
    remaining credits."""
    matches = db.query(
        "SELECT * FROM minigrid_accounts WHERE account_id = ? OR phone = ?",
        (identifier, identifier),
    )
    if not matches:
        raise HTTPException(status_code=404, detail=f"No customer for {identifier!r}")
    acct = matches[0]
    aid = acct["account_id"]
    bal = db.query(
        "SELECT ending_balance_credits FROM credit_balances "
        "WHERE account_id = ? ORDER BY month DESC LIMIT 1", (aid,)
    )
    charged = db.query(
        "SELECT COALESCE(SUM(-credits_delta), 0) AS c FROM billing_ledger "
        "WHERE account_id = ? AND event_type = 'cook_charge'", (aid,)
    )
    totals = db.query(
        "SELECT COALESCE(SUM(kwh), 0) AS kwh, COUNT(*) AS n "
        "FROM cooking_sessions WHERE account_id = ?", (aid,)
    )
    recent = db.query(
        "SELECT date, start_hour_eat, kwh, slot_color FROM cooking_sessions "
        "WHERE account_id = ? ORDER BY start_at DESC LIMIT 5", (aid,)
    )
    return {
        "account_id": aid,
        "account_type": acct["account_type"],
        "entity_id": acct["entity_id"],
        "phone": acct.get("phone"),
        "remaining_credits": bal[0]["ending_balance_credits"] if bal else 0,
        "total_charged_credits": charged[0]["c"] if charged else 0,
        "total_kwh": round(totals[0]["kwh"], 3) if totals else 0.0,
        "session_count": totals[0]["n"] if totals else 0,
        "recent_sessions": recent,
    }


@app.get(f"{API_PREFIX}/accounts/{{account_id}}/cookers", tags=["accounts"])
def account_cookers(account_id: str) -> dict[str, Any]:
    _get_one("minigrid_accounts", "account_id", account_id, "Account")
    rows = db.select_rows("cooker_assets", {"account_id": account_id}, order_by="cooker_id")
    return {"count": len(rows), "results": rows}


@app.get(f"{API_PREFIX}/accounts/{{account_id}}/sessions", tags=["accounts"])
def account_sessions(
    account_id: str,
    date: str | None = None,
    slot_color: str | None = None,
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    _get_one("minigrid_accounts", "account_id", account_id, "Account")
    filters = {"account_id": account_id, "date": date, "slot_color": slot_color}
    return _paginated("cooking_sessions", filters, "start_at", limit, offset)


@app.get(f"{API_PREFIX}/accounts/{{account_id}}/daily-behavior", tags=["accounts"])
def account_daily_behavior(account_id: str, date: str | None = None) -> dict[str, Any]:
    _get_one("minigrid_accounts", "account_id", account_id, "Account")
    filters = {"account_id": account_id, "date": date}
    rows = db.select_rows("account_daily_behavior", filters, order_by="date")
    return {"count": len(rows), "results": rows}


@app.get(f"{API_PREFIX}/accounts/{{account_id}}/billing", tags=["accounts"])
def account_billing(
    account_id: str,
    event_type: str | None = None,
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    _get_one("minigrid_accounts", "account_id", account_id, "Account")
    filters = {"account_id": account_id, "event_type": event_type}
    return _paginated("billing_ledger", filters, "created_at", limit, offset)


@app.get(f"{API_PREFIX}/accounts/{{account_id}}/credit-balance", tags=["accounts"])
def account_credit_balance(account_id: str) -> dict[str, Any]:
    _get_one("minigrid_accounts", "account_id", account_id, "Account")
    return _get_one("credit_balances", "account_id", account_id, "Credit balance")


@app.get(f"{API_PREFIX}/accounts/{{account_id}}/wallet", tags=["accounts"])
def account_wallet(account_id: str) -> dict[str, Any]:
    """Live earned-credit wallet: fractional credits accrue and realize at 1.0."""
    _get_one("minigrid_accounts", "account_id", account_id, "Account")
    rows = db.select_rows("credit_wallet", {"account_id": account_id}, limit=1)
    if rows:
        row = rows[0]
        total = float(row["accumulated_credit"])
        awarded = int(row["credits_awarded"])
        return {
            "account_id": account_id,
            "accumulated_credit": round(total, 3),
            "credits_awarded": awarded,
            "progress_to_next_credit": round(total - awarded, 3),
            "updated_at": row["updated_at"],
        }
    return {
        "account_id": account_id,
        "accumulated_credit": 0.0,
        "credits_awarded": 0,
        "progress_to_next_credit": 0.0,
        "updated_at": None,
    }


@app.get(f"{API_PREFIX}/accounts/{{account_id}}/usage-summary", tags=["accounts"])
def account_usage_summary(account_id: str) -> dict[str, Any]:
    """Aggregate energy usage for the account over the dataset month.

    One number per account: total kWh, sessions, active days, and the green-window
    share - the monthly view the per-session / per-day endpoints only expose in raw
    rows.
    """
    _get_one("minigrid_accounts", "account_id", account_id, "Account")
    rows = db.query(
        "SELECT COUNT(*) AS sessions, "
        "COALESCE(SUM(kwh), 0) AS total_kwh, "
        "COUNT(DISTINCT date) AS active_days, "
        "MIN(date) AS period_start, MAX(date) AS period_end, "
        "SUM(CASE WHEN slot_color = 'green' THEN 1 ELSE 0 END) AS green_sessions "
        "FROM cooking_sessions WHERE account_id = ?",
        [account_id],
    )
    row = rows[0] if rows else {}
    sessions = int(row.get("sessions") or 0)
    total_kwh = float(row.get("total_kwh") or 0.0)
    active_days = int(row.get("active_days") or 0)
    green_sessions = int(row.get("green_sessions") or 0)
    return {
        "account_id": account_id,
        "period_start": row.get("period_start"),
        "period_end": row.get("period_end"),
        "total_kwh": round(total_kwh, 3),
        "sessions": sessions,
        "active_days": active_days,
        "avg_daily_kwh": round(total_kwh / active_days, 3) if active_days else 0.0,
        "avg_session_kwh": round(total_kwh / sessions, 3) if sessions else 0.0,
        "green_sessions": green_sessions,
        "green_session_share": round(green_sessions / sessions, 3) if sessions else 0.0,
    }


@app.get(f"{API_PREFIX}/accounts/{{account_id}}/recommendation", tags=["recommendations"])
def account_recommendation(
    account_id: str,
    top: int = Query(scoring.DEFAULT_TOP_WINDOWS, ge=1, le=24),
    date: str | None = Query(None, description="Plan date for shared-grid capacity; defaults to today"),
) -> dict[str, Any]:
    account = _get_one("minigrid_accounts", "account_id", account_id, "Account")
    behavior = db.select_rows(
        "account_daily_behavior", {"account_id": account_id}, order_by="date DESC", limit=1
    )
    latest = behavior[0] if behavior else {}
    plan_date = date or _today()

    # Model produces the full 24-hour day (community + per-account history).
    live = ml_client.account_recommendations(account_id, 24)
    if live is not None and live.get("all_windows"):
        base_windows = live["all_windows"]
        source = live.get("model_version", "model")
    else:
        base_windows = sorted(scoring.rank_cooking_windows(), key=lambda w: w["hour_eat"])
        source = base_windows[0].get("model_version") if base_windows else None

    # Overlay live shared-grid capacity so hours others already committed to are
    # down-weighted for this user.
    all_windows = capacity.adjust_windows(base_windows, plan_date)
    all_windows.sort(key=lambda window: window["hour_eat"])
    windows = capacity.adjust_and_rank(base_windows, plan_date)[:top]

    best = windows[0]["window"] if windows else None
    return {
        "account_id": account_id,
        "account_type": account["account_type"],
        "date": plan_date,
        "current_preferred_hour": latest.get("preferred_cooking_hour"),
        "recent_green_window_share": latest.get("green_window_share"),
        "model_version": source,
        "recommended_windows": windows,
        "all_windows": all_windows,
        "message": (
            f"Shift cooking towards {best} for the best reward window."
            if best else "No grid data available to recommend a window."
        ),
    }


# --------------------------------------------------------------------------- #
# Cookers
# --------------------------------------------------------------------------- #

@app.get(f"{API_PREFIX}/cookers", tags=["cookers"])
def list_cookers(
    account_id: str | None = None,
    account_type: str | None = None,
    source: str | None = Query(None, description="observed_smartplug or synthetic_profile"),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    filters = {"account_id": account_id, "account_type": account_type, "source": source}
    return _paginated("cooker_assets", filters, "cooker_id", limit, offset)


@app.get(f"{API_PREFIX}/cookers/{{cooker_id}}", tags=["cookers"])
def get_cooker(cooker_id: str) -> dict[str, Any]:
    return _get_one("cooker_assets", "cooker_id", cooker_id, "Cooker")


@app.get(f"{API_PREFIX}/cookers/{{cooker_id}}/utilization", tags=["cookers"])
def cooker_utilization(cooker_id: str, date: str | None = None) -> dict[str, Any]:
    _get_one("cooker_assets", "cooker_id", cooker_id, "Cooker")
    filters = {"cooker_id": cooker_id, "date": date}
    rows = db.select_rows("cooker_utilization_daily", filters, order_by="date")
    return {"count": len(rows), "results": rows}


# --------------------------------------------------------------------------- #
# Cooking sessions
# --------------------------------------------------------------------------- #

@app.get(f"{API_PREFIX}/sessions", tags=["sessions"])
def list_sessions(
    account_id: str | None = None,
    cooker_id: str | None = None,
    date: str | None = None,
    slot_color: str | None = None,
    source: str | None = None,
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    filters = {
        "account_id": account_id,
        "cooker_id": cooker_id,
        "date": date,
        "slot_color": slot_color,
        "source": source,
    }
    return _paginated("cooking_sessions", filters, "start_at", limit, offset)


@app.get(f"{API_PREFIX}/sessions/{{session_id}}", tags=["sessions"])
def get_session(session_id: str) -> dict[str, Any]:
    return _get_one("cooking_sessions", "session_id", session_id, "Session")


# --------------------------------------------------------------------------- #
# Grid telemetry and recommendations
# --------------------------------------------------------------------------- #

@app.get(f"{API_PREFIX}/grid/hourly", tags=["grid"])
def grid_hourly(
    date: str | None = None,
    hour: int | None = Query(None, ge=0, le=23),
    slot_color: str | None = None,
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    filters = {"date": date, "hour_eat": hour, "slot_color": slot_color}
    return _paginated("grid_hourly", filters, "timestamp_hour", limit, offset)


@app.get(f"{API_PREFIX}/grid/daily-plan", tags=["grid"])
def grid_daily_plan(
    date: str | None = Query(None, description="Plan date for shared-grid capacity; defaults to today"),
) -> dict[str, Any]:
    """Per hour-of-day cooking plan with live shared-grid capacity overlaid."""
    plan_date = date or _today()
    windows = capacity.adjust_windows(scoring.rank_cooking_windows(), plan_date)
    by_hour = sorted(windows, key=lambda window: window["hour_eat"])
    return {"date": plan_date, "count": len(by_hour), "results": by_hour}


@app.get(f"{API_PREFIX}/grid/capacity", tags=["grid"])
def grid_capacity(
    date: str | None = Query(None, description="Date to report committed load for; defaults to today"),
) -> dict[str, Any]:
    """Per-hour shared-grid capacity, committed load, and remaining headroom."""
    plan_date = date or _today()
    capacity_by_hour = capacity.capacity_kwh_by_hour()
    load = capacity.committed_load(plan_date)
    hours = []
    for hour in range(24):
        cap = capacity_by_hour.get(hour, 0.0)
        committed_kwh = load[hour]["kwh"]
        hours.append({
            "hour_eat": hour,
            "window": f"{hour:02d}:00-{(hour + 1) % 24:02d}:00",
            "capacity_kwh": round(cap, 3),
            "committed_kwh": round(committed_kwh, 3),
            "headroom_kwh": round(max(cap - committed_kwh, 0.0), 3),
            "committed_cookers": load[hour]["cookers"],
        })
    return {"date": plan_date, "count": len(hours), "results": hours}


@app.get(f"{API_PREFIX}/recommendations", tags=["recommendations"])
def recommendations(
    top: int = Query(scoring.DEFAULT_TOP_WINDOWS, ge=1, le=24),
    date: str | None = Query(None, description="Plan date for shared-grid capacity; defaults to today"),
) -> dict[str, Any]:
    """Grid-level best cooking windows with live capacity overlaid (community-wide)."""
    plan_date = date or _today()
    windows = capacity.adjust_and_rank(scoring.rank_cooking_windows(), plan_date)[:top]
    return {"date": plan_date, "count": len(windows), "results": windows}


# --------------------------------------------------------------------------- #
# Cooking plans (write): a user chooses a cooking time and gets a credit estimate
# --------------------------------------------------------------------------- #

@app.post(f"{API_PREFIX}/cooking-plans", status_code=201, tags=["cooking-plans"])
def create_cooking_plan(plan: CookingPlanRequest) -> dict[str, Any]:
    """Book a chosen cooking time and return the suggested credit gain.

    The `suggested_credit_gain`, `credit_gain_basis`, and `model_version` fields
    are produced by the credit model (currently a rules baseline, AI-ready).
    """
    _get_one("minigrid_accounts", "account_id", plan.account_id, "Account")
    if plan.cooker_id is not None:
        _get_one("cooker_assets", "cooker_id", plan.cooker_id, "Cooker")

    assessment = _capacity_aware_assessment(
        plan.account_id, plan.date, plan.start_hour_eat, plan.planned_duration_minutes
    )
    record = {
        "plan_id": f"PLAN-{uuid.uuid4().hex[:8]}",
        "account_id": plan.account_id,
        "cooker_id": plan.cooker_id,
        "date": plan.date,
        "start_hour_eat": plan.start_hour_eat,
        "planned_duration_minutes": plan.planned_duration_minutes,
        "slot_color": assessment["slot_color"],
        "expected_kwh": assessment["expected_kwh"],
        "suggested_credit_gain": assessment["suggested_credit_gain"],
        "credit_gain_basis": assessment["credit_gain_basis"],
        "model_version": assessment["model_version"],
        "status": PLAN_STATUS_PLANNED,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    db.insert_row("cooking_plans", record)
    return {**record, "assessment": assessment}


@app.get(f"{API_PREFIX}/cooking-plans", tags=["cooking-plans"])
def list_cooking_plans(
    account_id: str | None = None,
    status: str | None = None,
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    filters = {"account_id": account_id, "status": status}
    return _paginated("cooking_plans", filters, "created_at DESC", limit, offset)


@app.get(f"{API_PREFIX}/cooking-plans/{{plan_id}}", tags=["cooking-plans"])
def get_cooking_plan(plan_id: str) -> dict[str, Any]:
    return _get_one("cooking_plans", "plan_id", plan_id, "Cooking plan")


@app.post(f"{API_PREFIX}/cooking-plans/{{plan_id}}/status", tags=["cooking-plans"])
def update_cooking_plan_status(plan_id: str, update: PlanStatusUpdate) -> dict[str, Any]:
    """Confirm or cancel a previously created plan."""
    allowed = {PLAN_STATUS_PLANNED, PLAN_STATUS_CONFIRMED, PLAN_STATUS_CANCELLED}
    if update.status not in allowed:
        raise HTTPException(status_code=422, detail=f"status must be one of {sorted(allowed)}")
    _get_one("cooking_plans", "plan_id", plan_id, "Cooking plan")
    db.update_value("cooking_plans", "plan_id", plan_id, "status", update.status)
    return _get_one("cooking_plans", "plan_id", plan_id, "Cooking plan")


# --------------------------------------------------------------------------- #
# Live sessions (write): a user actually cooks -> record usage + feed learning
# --------------------------------------------------------------------------- #

@app.post(f"{API_PREFIX}/sessions", status_code=201, tags=["sessions"])
def record_session(session: SessionRecordRequest,
                   background_tasks: BackgroundTasks) -> dict[str, Any]:
    """Record an actual cooking session on the shared grid.

    Persists the session durably, appends it to the ML-readable live-sessions
    file, and increments the continual-learning counter. Once
    ``GRIDCOOK_RETRAIN_EVERY`` sessions accrue, a background retrain is fired so
    the next user's recommendations reflect the newest community data.
    """
    account = _get_one("minigrid_accounts", "account_id", session.account_id, "Account")
    if session.cooker_id is not None:
        _get_one("cooker_assets", "cooker_id", session.cooker_id, "Cooker")

    # Score against grid state *before* this session is added to committed load.
    assessment = _capacity_aware_assessment(
        session.account_id, session.date, session.start_hour_eat, session.duration_minutes
    )
    kwh = session.kwh if session.kwh is not None else (
        assessment["expected_kwh"] or DEFAULT_SESSION_KWH
    )
    shifted = int(
        DAYTIME_START_HOUR <= session.start_hour_eat <= DAYTIME_END_HOUR
        and assessment["slot_color"] != scoring.SLOT_RED
    )
    now = datetime.now(timezone.utc).isoformat()
    record = {
        "session_id": f"SESS-{uuid.uuid4().hex[:8]}",
        "account_id": session.account_id,
        "cooker_id": session.cooker_id,
        "date": session.date,
        "start_hour_eat": session.start_hour_eat,
        "duration_minutes": session.duration_minutes,
        "kwh": round(float(kwh), 3),
        "slot_color": assessment["slot_color"],
        "suggested_credit_gain": assessment["suggested_credit_gain"],
        "credit_gain_basis": assessment["credit_gain_basis"],
        "model_version": assessment["model_version"],
        "shifted_daytime": shifted,
        "source": "live_api",
        "created_at": now,
    }
    db.insert_row("cooking_sessions_live", record)
    _append_live_session_csv({
        **record,
        "entity_id": account.get("entity_id", session.account_id),
        "account_type": account.get("account_type", ""),
        "start_at": f"{session.date}T{session.start_hour_eat:02d}:00:00",
    })

    # Fractional credit accrues to the account wallet; whole credits realize at 1.0.
    wallet = db.award_session_credit(session.account_id, record["suggested_credit_gain"])

    count = db.bump_sessions_since_train(1)
    retrain_triggered = count >= RETRAIN_EVERY
    if retrain_triggered:
        db.reset_sessions_since_train()
        background_tasks.add_task(_run_retrain_and_record)

    return {
        **record,
        "assessment": assessment,
        "wallet": wallet,
        "sessions_since_train": 0 if retrain_triggered else count,
        "retrain_triggered": retrain_triggered,
    }


@app.get(f"{API_PREFIX}/learning/state", tags=["learning"])
def learning_state() -> dict[str, Any]:
    """Continual-learning bookkeeping: sessions since last retrain + live job status.

    Retraining is kicked off automatically once ``retrain_every`` sessions accrue
    (no manual endpoint needed); this is the read-only view of that loop.
    """
    state = db.get_train_state()
    return {
        "sessions_since_train": state["sessions_since_train"],
        "retrain_every": RETRAIN_EVERY,
        "last_trained_version": state["last_trained_version"],
        "last_trained_at": state["last_trained_at"],
        "live_sessions_recorded": db.count_rows("cooking_sessions_live"),
        "ml_retrain": ml_client.retrain_status(),
    }


# --------------------------------------------------------------------------- #
# Billing, credit balances, leaderboard
# --------------------------------------------------------------------------- #

@app.get(f"{API_PREFIX}/billing", tags=["billing"])
def list_billing(
    account_id: str | None = None,
    event_type: str | None = None,
    session_id: str | None = None,
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    filters = {"account_id": account_id, "event_type": event_type, "session_id": session_id}
    return _paginated("billing_ledger", filters, "created_at", limit, offset)


@app.get(f"{API_PREFIX}/credit-balances", tags=["billing"])
def list_credit_balances(
    account_type: str | None = None,
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    filters = {"account_type": account_type}
    return _paginated("credit_balances", filters, "ending_balance_credits DESC", limit, offset)


# --------------------------------------------------------------------------- #
# Writes: session billing + wallet top-up (persistent DB mode only).
# Atomic — backed by Ezra's oloika_write; see data/DB_CONTRACT.md. Each write
# uses a short-lived writer connection and commits (oloika_write does not commit
# internally). Exceptions map to the HTTP codes named in the contract.
# --------------------------------------------------------------------------- #

class SessionCompleteRequest(BaseModel):
    session_id: str
    account_id: str
    kwh: float = Field(..., ge=0)
    slot_color: str = Field(..., pattern="^(green|orange|red)$")
    cooker_id: str | None = None
    shifted_daytime: int = Field(0, ge=0, le=1)
    start_at: str | None = None


class TopUpRequest(BaseModel):
    cash_kes: int = Field(..., gt=0)


def _writer():
    db_path = _os.environ.get("GRIDCOOK_DB_PATH")
    if oloika_write is None or not db_path:
        raise HTTPException(
            status_code=503,
            detail="Write path unavailable: set GRIDCOOK_DB_PATH + GRIDCOOK_DBTOOLS "
                   "(persistent DB mode). Reads still work in in-memory mode.",
        )
    return oloika_write.connect(db_path)


def _http_for(exc: Exception) -> HTTPException:
    mapping = [
        ("InsufficientCredits", 402),
        ("SessionAlreadyBilled", 409),
        ("UnknownAccount", 404),
        ("WriteError", 400),
    ]
    for name, code in mapping:
        cls = getattr(oloika_write, name, None)
        if cls is not None and isinstance(exc, cls):
            return HTTPException(status_code=code, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


@app.post(f"{API_PREFIX}/sessions/complete", status_code=201, tags=["writes"])
def complete_cooking_session(req: SessionCompleteRequest) -> dict[str, Any]:
    """Bill a finished cooking session: charge kWh + award the window reward +
    update the wallet, atomically; then refresh the leaderboard."""
    con = _writer()
    try:
        result = oloika_write.complete_session(
            con,
            session_id=req.session_id,
            account_id=req.account_id,
            kwh=req.kwh,
            slot_color=req.slot_color,
            cooker_id=req.cooker_id,
            shifted_daytime=req.shifted_daytime,
            start_at=req.start_at,
        )
        con.commit()
    except Exception as exc:  # noqa: BLE001 - re-raised as HTTP below
        con.rollback()
        con.close()
        raise _http_for(exc)
    # Leaderboard refresh runs in its own transaction (contract: not inside
    # complete_session). Best-effort — a stale board must not fail the cook.
    try:
        oloika_write.refresh_leaderboard(con)
        con.commit()
    except Exception:  # pragma: no cover
        con.rollback()
    finally:
        con.close()
    return result


@app.post(f"{API_PREFIX}/accounts/{{account_id}}/top-up", status_code=201, tags=["writes"])
def account_top_up(account_id: str, req: TopUpRequest) -> dict[str, Any]:
    """Add prepaid credit to an account's wallet (atomic)."""
    con = _writer()
    try:
        result = oloika_write.top_up(con, account_id, req.cash_kes)
        con.commit()
        return result
    except Exception as exc:  # noqa: BLE001
        con.rollback()
        raise _http_for(exc)
    finally:
        con.close()


@app.get(f"{API_PREFIX}/leaderboard", tags=["leaderboard"])
def leaderboard(
    leaderboard_group: str | None = Query(None, description="household or commercial group"),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    filters = {"leaderboard_group": leaderboard_group}
    return _paginated("leaderboard", filters, "rank", limit, offset)


# --------------------------------------------------------------------------- #
# Personas: households, commercial profiles, people
# --------------------------------------------------------------------------- #

@app.get(f"{API_PREFIX}/households", tags=["personas"])
def list_households(
    primary_equipment: str | None = None,
    meter_status: str | None = None,
    is_minigrid_user: str | None = None,
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    filters = {
        "primary_equipment": primary_equipment,
        "meter_status": meter_status,
        "is_minigrid_user": is_minigrid_user,
    }
    return _paginated("households", filters, "household_id", limit, offset)


@app.get(f"{API_PREFIX}/households/{{household_id}}", tags=["personas"])
def get_household(household_id: str) -> dict[str, Any]:
    return _get_one("households", "household_id", household_id, "Household")


@app.get(f"{API_PREFIX}/households/{{household_id}}/people", tags=["personas"])
def household_people(household_id: str) -> dict[str, Any]:
    _get_one("households", "household_id", household_id, "Household")
    rows = db.select_rows("people", {"household_id": household_id}, order_by="person_id")
    return {"count": len(rows), "results": rows}


@app.get(f"{API_PREFIX}/commercial-profiles", tags=["personas"])
def list_commercial_profiles(
    business_type: str | None = None,
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    filters = {"business_type": business_type}
    return _paginated("commercial_profiles", filters, "business_id", limit, offset)


@app.get(f"{API_PREFIX}/commercial-profiles/{{business_id}}", tags=["personas"])
def get_commercial_profile(business_id: str) -> dict[str, Any]:
    return _get_one("commercial_profiles", "business_id", business_id, "Business")


@app.get(f"{API_PREFIX}/people", tags=["personas"])
def list_people(
    household_id: str | None = None,
    gender: str | None = None,
    age_band: str | None = None,
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    filters = {"household_id": household_id, "gender": gender, "age_band": age_band}
    return _paginated("people", filters, "person_id", limit, offset)
