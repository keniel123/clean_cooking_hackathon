"""Generate example JSON responses and a Postman collection for the GridCook API.

Calls a running instance of the API, saves one example response per endpoint to
``apps/api/examples/``, and builds a Postman v2.1 collection (with those
responses embedded as examples) at
``apps/api/postman/gridcook_api.postman_collection.json``.

Because the collection ships real example responses, it can be imported into
Postman and served directly from a Postman **mock server** without a backend.

Usage:
    # In one terminal
    uvicorn gridcook.main:app --port 8000
    # In another
    python3 scripts/build_api_examples.py --base-url http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

API_DIR = Path(__file__).resolve().parents[1]
EXAMPLES_DIR = API_DIR / "examples"
POSTMAN_DIR = API_DIR / "postman"
COLLECTION_PATH = POSTMAN_DIR / "gridcook_api.postman_collection.json"

PREFIX = "/api/v1"
JSON_HEADER = [{"key": "Content-Type", "value": "application/json"}]


def _call(base_url: str, method: str, path: str, body: dict[str, Any] | None) -> tuple[int, Any]:
    url = base_url.rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    if body is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode())


def _url_object(path: str) -> dict[str, Any]:
    base, _, query = path.partition("?")
    segments = [segment for segment in base.strip("/").split("/") if segment]
    url: dict[str, Any] = {
        "raw": "{{baseUrl}}" + path,
        "host": ["{{baseUrl}}"],
        "path": segments,
    }
    if query:
        pairs = [pair.split("=", 1) for pair in query.split("&")]
        url["query"] = [{"key": key, "value": value} for key, value in pairs]
    return url


def _request_object(method: str, path: str, body: dict[str, Any] | None) -> dict[str, Any]:
    request: dict[str, Any] = {"method": method, "header": [], "url": _url_object(path)}
    if body is not None:
        request["header"] = list(JSON_HEADER)
        request["body"] = {
            "mode": "raw",
            "raw": json.dumps(body, indent=2),
            "options": {"raw": {"language": "json"}},
        }
    return request


def _postman_item(name: str, method: str, path: str, body: dict[str, Any] | None,
                  status_code: int, response_body: Any) -> dict[str, Any]:
    request = _request_object(method, path, body)
    return {
        "name": name,
        "request": request,
        "response": [
            {
                "name": f"{name} ({status_code})",
                "originalRequest": request,
                "status": "OK" if status_code < 300 else "Error",
                "code": status_code,
                "_postman_previewlanguage": "json",
                "header": list(JSON_HEADER),
                "body": json.dumps(response_body, indent=2),
            }
        ],
    }


def _discover(base_url: str) -> dict[str, str]:
    """Fetch real IDs so path-parameter examples reference existing records."""
    _, leaderboard = _call(base_url, "GET", f"{PREFIX}/leaderboard?limit=1", None)
    account_id = leaderboard["results"][0]["account_id"]

    _, households_accounts = _call(
        base_url, "GET", f"{PREFIX}/accounts?account_type=household&limit=1", None
    )
    household_account_id = households_accounts["results"][0]["account_id"]

    _, cookers = _call(base_url, "GET", f"{PREFIX}/accounts/{account_id}/cookers", None)
    cooker_id = cookers["results"][0]["cooker_id"]

    _, sessions = _call(base_url, "GET", f"{PREFIX}/accounts/{account_id}/sessions?limit=1", None)
    session_id = sessions["results"][0]["session_id"]

    _, households = _call(base_url, "GET", f"{PREFIX}/households?limit=1", None)
    household_id = households["results"][0]["household_id"]

    _, businesses = _call(base_url, "GET", f"{PREFIX}/commercial-profiles?limit=1", None)
    business_id = businesses["results"][0]["business_id"]

    return {
        "account_id": account_id,
        "household_account_id": household_account_id,
        "cooker_id": cooker_id,
        "session_id": session_id,
        "household_id": household_id,
        "business_id": business_id,
    }


def _endpoint_specs(ids: dict[str, str], plan_id: str) -> list[dict[str, Any]]:
    account = ids["account_id"]
    return [
        {"folder": "Meta & stats", "name": "Health", "file": "health",
         "method": "GET", "path": "/health"},
        {"folder": "Meta & stats", "name": "Dataset summary", "file": "stats_summary",
         "method": "GET", "path": f"{PREFIX}/stats/summary"},
        {"folder": "Meta & stats", "name": "Persona summary", "file": "stats_personas",
         "method": "GET", "path": f"{PREFIX}/stats/personas"},

        {"folder": "Accounts", "name": "List accounts", "file": "accounts_list",
         "method": "GET", "path": f"{PREFIX}/accounts?limit=3"},
        {"folder": "Accounts", "name": "Get account", "file": "account",
         "method": "GET", "path": f"{PREFIX}/accounts/{account}"},
        {"folder": "Accounts", "name": "Account cookers", "file": "account_cookers",
         "method": "GET", "path": f"{PREFIX}/accounts/{account}/cookers"},
        {"folder": "Accounts", "name": "Account sessions", "file": "account_sessions",
         "method": "GET", "path": f"{PREFIX}/accounts/{account}/sessions?limit=3"},
        {"folder": "Accounts", "name": "Account daily behavior", "file": "account_daily_behavior",
         "method": "GET", "path": f"{PREFIX}/accounts/{account}/daily-behavior"},
        {"folder": "Accounts", "name": "Account billing", "file": "account_billing",
         "method": "GET", "path": f"{PREFIX}/accounts/{account}/billing?limit=3"},
        {"folder": "Accounts", "name": "Account credit balance", "file": "account_credit_balance",
         "method": "GET", "path": f"{PREFIX}/accounts/{account}/credit-balance"},
        {"folder": "Accounts", "name": "Account recommendation", "file": "account_recommendation",
         "method": "GET", "path": f"{PREFIX}/accounts/{account}/recommendation?top=3"},

        {"folder": "Cookers", "name": "List cookers", "file": "cookers_list",
         "method": "GET", "path": f"{PREFIX}/cookers?limit=3"},
        {"folder": "Cookers", "name": "Get cooker", "file": "cooker",
         "method": "GET", "path": f"{PREFIX}/cookers/{ids['cooker_id']}"},
        {"folder": "Cookers", "name": "Cooker utilization", "file": "cooker_utilization",
         "method": "GET", "path": f"{PREFIX}/cookers/{ids['cooker_id']}/utilization"},

        {"folder": "Sessions", "name": "List sessions", "file": "sessions_list",
         "method": "GET", "path": f"{PREFIX}/sessions?limit=3"},
        {"folder": "Sessions", "name": "Get session", "file": "session",
         "method": "GET", "path": f"{PREFIX}/sessions/{ids['session_id']}"},

        {"folder": "Grid & recommendations", "name": "Grid hourly", "file": "grid_hourly",
         "method": "GET", "path": f"{PREFIX}/grid/hourly?limit=3"},
        {"folder": "Grid & recommendations", "name": "Grid daily plan", "file": "grid_daily_plan",
         "method": "GET", "path": f"{PREFIX}/grid/daily-plan"},
        {"folder": "Grid & recommendations", "name": "Recommendations", "file": "recommendations",
         "method": "GET", "path": f"{PREFIX}/recommendations?top=3"},

        {"folder": "Cooking plans", "name": "Create cooking plan", "file": "cooking_plan_created",
         "method": "POST", "path": f"{PREFIX}/cooking-plans",
         "body": {"account_id": ids["household_account_id"], "date": "2025-06-15",
                  "start_hour_eat": 11, "cooker_id": None, "planned_duration_minutes": 45}},
        {"folder": "Cooking plans", "name": "List cooking plans", "file": "cooking_plans_list",
         "method": "GET", "path": f"{PREFIX}/cooking-plans?limit=3"},
        {"folder": "Cooking plans", "name": "Get cooking plan", "file": "cooking_plan",
         "method": "GET", "path": f"{PREFIX}/cooking-plans/{plan_id}"},
        {"folder": "Cooking plans", "name": "Update plan status", "file": "cooking_plan_status",
         "method": "POST", "path": f"{PREFIX}/cooking-plans/{plan_id}/status",
         "body": {"status": "confirmed"}},

        {"folder": "Billing & leaderboard", "name": "List billing", "file": "billing_list",
         "method": "GET", "path": f"{PREFIX}/billing?limit=3"},
        {"folder": "Billing & leaderboard", "name": "Credit balances", "file": "credit_balances_list",
         "method": "GET", "path": f"{PREFIX}/credit-balances?limit=3"},
        {"folder": "Billing & leaderboard", "name": "Leaderboard", "file": "leaderboard",
         "method": "GET", "path": f"{PREFIX}/leaderboard?limit=5"},

        {"folder": "Personas", "name": "List households", "file": "households_list",
         "method": "GET", "path": f"{PREFIX}/households?limit=3"},
        {"folder": "Personas", "name": "Get household", "file": "household",
         "method": "GET", "path": f"{PREFIX}/households/{ids['household_id']}"},
        {"folder": "Personas", "name": "Household people", "file": "household_people",
         "method": "GET", "path": f"{PREFIX}/households/{ids['household_id']}/people"},
        {"folder": "Personas", "name": "List commercial profiles", "file": "commercial_profiles_list",
         "method": "GET", "path": f"{PREFIX}/commercial-profiles?limit=3"},
        {"folder": "Personas", "name": "Get commercial profile", "file": "commercial_profile",
         "method": "GET", "path": f"{PREFIX}/commercial-profiles/{ids['business_id']}"},
        {"folder": "Personas", "name": "List people", "file": "people_list",
         "method": "GET", "path": f"{PREFIX}/people?limit=3"},
    ]


def build(base_url: str) -> None:
    EXAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    POSTMAN_DIR.mkdir(parents=True, exist_ok=True)

    ids = _discover(base_url)

    # Seed one plan so the "get plan" / "update status" examples reference a real id.
    _, created = _call(base_url, "POST", f"{PREFIX}/cooking-plans", {
        "account_id": ids["household_account_id"], "date": "2025-06-15",
        "start_hour_eat": 11, "cooker_id": None, "planned_duration_minutes": 45,
    })
    plan_id = created["plan_id"]

    folders: dict[str, list[dict[str, Any]]] = {}
    for spec in _endpoint_specs(ids, plan_id):
        body = spec.get("body")
        status_code, response_body = _call(base_url, spec["method"], spec["path"], body)
        (EXAMPLES_DIR / f"{spec['file']}.json").write_text(
            json.dumps(response_body, indent=2) + "\n", encoding="utf-8"
        )
        item = _postman_item(spec["name"], spec["method"], spec["path"], body,
                             status_code, response_body)
        folders.setdefault(spec["folder"], []).append(item)

    collection = {
        "info": {
            "_postman_id": str(uuid.uuid4()),
            "name": "GridCook Oloika API",
            "description": "Mockable REST API for the Oloika June 2025 clean-cooking dataset.",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "variable": [{"key": "baseUrl", "value": "http://127.0.0.1:8000"}],
        "item": [{"name": name, "item": items} for name, items in folders.items()],
    }
    COLLECTION_PATH.write_text(json.dumps(collection, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(list(EXAMPLES_DIR.glob('*.json')))} example files to {EXAMPLES_DIR}")
    print(f"Wrote Postman collection to {COLLECTION_PATH}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    build(args.base_url)


if __name__ == "__main__":
    main()
