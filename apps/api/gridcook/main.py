"""GridCook Oloika REST API.

Serves the documented Oloika June 2025 synthetic dataset over RESTful,
resource-oriented endpoints, plus a rules-first "best time to cook"
recommendation engine.

Run locally:

    uvicorn gridcook.main:app --reload --port 8000

Interactive docs are then available at http://127.0.0.1:8000/docs
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import db, scoring

API_PREFIX = "/api/v1"
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 500

PLAN_STATUS_PLANNED = "planned"
PLAN_STATUS_CONFIRMED = "confirmed"
PLAN_STATUS_CANCELLED = "cancelled"

app = FastAPI(
    title="GridCook Oloika API",
    version="1.0.0",
    description="RESTful access to the Oloika June 2025 clean-cooking dataset.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
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


@app.get(f"{API_PREFIX}/accounts/{{account_id}}/recommendation", tags=["recommendations"])
def account_recommendation(
    account_id: str,
    top: int = Query(scoring.DEFAULT_TOP_WINDOWS, ge=1, le=24),
) -> dict[str, Any]:
    account = _get_one("minigrid_accounts", "account_id", account_id, "Account")
    behavior = db.select_rows(
        "account_daily_behavior", {"account_id": account_id}, order_by="date DESC", limit=1
    )
    latest = behavior[0] if behavior else {}
    windows = scoring.top_cooking_windows(top)
    best = windows[0]["window"] if windows else None
    return {
        "account_id": account_id,
        "account_type": account["account_type"],
        "current_preferred_hour": latest.get("preferred_cooking_hour"),
        "recent_green_window_share": latest.get("green_window_share"),
        "recommended_windows": windows,
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
def grid_daily_plan() -> dict[str, Any]:
    """Per hour-of-day cooking plan ranked by favorability across the month."""
    windows = scoring.rank_cooking_windows()
    by_hour = sorted(windows, key=lambda window: window["hour_eat"])
    return {"count": len(by_hour), "results": by_hour}


@app.get(f"{API_PREFIX}/recommendations", tags=["recommendations"])
def recommendations(top: int = Query(scoring.DEFAULT_TOP_WINDOWS, ge=1, le=24)) -> dict[str, Any]:
    """Grid-level best cooking windows (not tied to a specific account)."""
    windows = scoring.top_cooking_windows(top)
    return {"count": len(windows), "results": windows}


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

    assessment = scoring.assess_cooking_time(plan.start_hour_eat, plan.planned_duration_minutes)
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
