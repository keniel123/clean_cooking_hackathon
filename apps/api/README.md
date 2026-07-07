# GridCook Oloika API

A lightweight, read-only REST API over the Oloika June 2025 synthetic dataset
(`data/synthetic/`). On startup it loads the documented CSV/JSON files into an
in-memory SQLite database, so no external database is required. It also exposes
a rules-first **best time to cook** recommendation engine derived from the
hourly grid telemetry.

## Run

```bash
cd apps/api
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn gridcook.main:app --reload --port 8000
```

Then open the interactive docs at http://127.0.0.1:8000/docs

The dataset location defaults to `<repo>/data/synthetic`. Override with:

```bash
GRIDCOOK_DATA_DIR=/path/to/synthetic uvicorn gridcook.main:app --port 8000
```

## Endpoints

Most endpoints are `GET` (read the dataset). Writes happen through the
**cooking-plans** resource: a user chooses a cooking time (`POST`), and the
response includes the AI-ready `suggested_credit_gain`.

All list endpoints support `limit` and `offset` pagination and return
`{ "count", "limit", "offset", "results" }`.

### Meta & stats
| Method | Path | Description |
| --- | --- | --- |
| GET | `/health` | Liveness check + account count |
| GET | `/api/v1/stats/summary` | Monthly dataset summary |
| GET | `/api/v1/stats/personas` | Persona / fuel-mix summary |
| GET | `/api/v1/stats/schema` | Machine-readable dataset schema |

### Accounts
| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/v1/accounts` | List mini-grid accounts (`account_type`, `community_id`, `meter_status`) |
| GET | `/api/v1/accounts/{account_id}` | Single account |
| GET | `/api/v1/accounts/{account_id}/cookers` | Cookers on the account |
| GET | `/api/v1/accounts/{account_id}/sessions` | Cooking sessions (`date`, `slot_color`) |
| GET | `/api/v1/accounts/{account_id}/daily-behavior` | Daily behavior features (`date`) |
| GET | `/api/v1/accounts/{account_id}/billing` | Billing ledger (`event_type`) |
| GET | `/api/v1/accounts/{account_id}/credit-balance` | End-of-month credit balance |
| GET | `/api/v1/accounts/{account_id}/recommendation` | Personalized best cooking windows |

### Cookers
| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/v1/cookers` | List cooker assets (`account_id`, `account_type`, `source`) |
| GET | `/api/v1/cookers/{cooker_id}` | Single cooker |
| GET | `/api/v1/cookers/{cooker_id}/utilization` | Daily utilization (`date`) |

### Sessions
| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/v1/sessions` | List sessions (`account_id`, `cooker_id`, `date`, `slot_color`, `source`) |
| GET | `/api/v1/sessions/{session_id}` | Single session |

### Grid & recommendations
| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/v1/grid/hourly` | Hourly grid telemetry (`date`, `hour`, `slot_color`) |
| GET | `/api/v1/grid/daily-plan` | Per hour-of-day cooking plan, ranked |
| GET | `/api/v1/recommendations` | Top grid-level cooking windows (`top`) |

### Cooking plans (write)
| Method | Path | Description |
| --- | --- | --- |
| POST | `/api/v1/cooking-plans` | Book a chosen cooking time; returns `suggested_credit_gain` |
| GET | `/api/v1/cooking-plans` | List booked plans (`account_id`, `status`) |
| GET | `/api/v1/cooking-plans/{plan_id}` | Single plan |
| POST | `/api/v1/cooking-plans/{plan_id}/status` | Confirm or cancel a plan |

Request body for `POST /api/v1/cooking-plans`:

```json
{
  "account_id": "HH-0007",
  "date": "2025-06-15",
  "start_hour_eat": 11,
  "cooker_id": null,
  "planned_duration_minutes": 45
}
```

Response (`201 Created`) — note the credit-model fields:

```json
{
  "plan_id": "PLAN-8d37e512",
  "account_id": "HH-0007",
  "date": "2025-06-15",
  "start_hour_eat": 11,
  "slot_color": "green",
  "expected_kwh": 1.059,
  "suggested_credit_gain": 19,
  "credit_gain_basis": "green window x1 on 1.06 kWh + 8 daytime-shift bonus",
  "model_version": "rules-v1",
  "status": "planned",
  "created_at": "2026-07-07T15:59:05Z",
  "assessment": { "is_optimal": true, "best_alternative": null, "reason": "..." }
}
```

### Billing & leaderboard
| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/v1/billing` | Billing ledger (`account_id`, `event_type`, `session_id`) |
| GET | `/api/v1/credit-balances` | Monthly credit balances (`account_type`) |
| GET | `/api/v1/leaderboard` | Leaderboard (`leaderboard_group`) |

### Personas
| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/v1/households` | Household personas (`primary_equipment`, `meter_status`, `is_minigrid_user`) |
| GET | `/api/v1/households/{household_id}` | Single household |
| GET | `/api/v1/households/{household_id}/people` | People in a household |
| GET | `/api/v1/commercial-profiles` | Commercial personas (`business_type`) |
| GET | `/api/v1/commercial-profiles/{business_id}` | Single business |
| GET | `/api/v1/people` | People (`household_id`, `gender`, `age_band`) |

## Response schemas

Every resource field is listed below. The machine-readable source of truth is
`data/synthetic/oloika_dataset_schema.json`, also served live at
`GET /api/v1/stats/schema`; a concrete example object for each endpoint lives in
`examples/*.json`. List endpoints wrap these objects in
`{ "count", "limit", "offset", "results": [ ... ] }`.

### Account (`/accounts`)
| Field | Type | Notes |
| --- | --- | --- |
| `account_id` | string | Primary key |
| `account_type` | string | `household` or `commercial` |
| `entity_id` | string | Household or business profile ID |
| `community_id` | string | e.g. `oloika` |
| `meter_status` | string | `metered` or `sub_metered` |

### Cooker (`/cookers`)
| Field | Type | Notes |
| --- | --- | --- |
| `cooker_id` | string | Primary key |
| `account_id` | string | FK → account |
| `entity_id` | string | |
| `account_type` | string | `household` or `commercial` |
| `plug` | string \| null | Observed smart-plug ID when available |
| `observed_group` | string \| null | Research group label |
| `asset_type` | string | Observed smart-plug or profile-estimated cooker |
| `source` | string | `observed_smartplug` or `synthetic_profile` |

### Cooking session (`/sessions`, `/accounts/{id}/sessions`)
| Field | Type | Notes |
| --- | --- | --- |
| `session_id` | string | Primary key |
| `account_id`, `entity_id`, `account_type` | string | Owner |
| `cooker_id`, `plug`, `observed_group` | string | Cooker linkage |
| `source` | string | `observed_smartplug` or `synthetic_profile` |
| `start_at`, `end_at` | string | ISO datetime (EAT) |
| `date` | string | `YYYY-MM-DD` |
| `start_hour_eat` | int | 0–23 |
| `duration_minutes` | float | |
| `kwh` | float | Observed/estimated energy |
| `avg_w`, `peak_w` | float / int | Power |
| `slot_color` | string | `green` / `orange` / `red` |
| `shifted_daytime` | int | 1 if in a daytime green/orange window |

### Cooker utilization (`/cookers/{id}/utilization`)
| Field | Type | Notes |
| --- | --- | --- |
| `date`, `cooker_id` | string | Composite key |
| `account_id`, `plug`, `source` | string | |
| `active_minutes`, `available_minutes`, `utilization_percent` | float | |
| `session_count`, `observed_sessions`, `synthetic_sessions` | int | |
| `green_sessions`, `orange_sessions`, `red_sessions` | int | |
| `kwh` | float | |
| `peak_concurrent_cookers` | int | |

### Account daily behavior (`/accounts/{id}/daily-behavior`)
| Field | Type | Notes |
| --- | --- | --- |
| `account_id`, `date` | string | Composite key |
| `entity_id`, `account_type` | string | |
| `sessions` | int | |
| `kwh` | float | |
| `preferred_cooking_hour` | string | |
| `green_window_share` | float | 0–1 |
| `red_window_sessions`, `shifted_daytime_sessions` | int | |
| `credits_earned`, `credits_spent` | int | |
| `fuel_stacking_risk_flag` | int | 0/1 |
| `green_sessions`, `orange_sessions`, `red_sessions` | int | |

### Grid hourly (`/grid/hourly`)
| Field | Type | Notes |
| --- | --- | --- |
| `timestamp_hour` | string | Primary key, ISO hour (EAT) |
| `date` | string | |
| `hour_eat` | int | 0–23 |
| `battery_soc_percent`, `battery_power_w` | float | |
| `pv_dc_power_w`, `pv_ac_power_w`, `fronius_pv_power_w` | float | PV sources |
| `ac_load_w`, `fronius_consumption_w` | float | Load |
| `voltage_avg_v` | float | |
| `system_alarm_count` | int | |
| `slot_color` | string | `green` / `orange` / `red` |
| `source` | string | Contributing telemetry sources |

### Recommendation window (`/recommendations`, `/grid/daily-plan`, `/accounts/{id}/recommendation`)
| Field | Type | Notes |
| --- | --- | --- |
| `hour_eat` | int | 0–23 |
| `window` | string | e.g. `11:00-12:00` |
| `slot_color` | string | Dominant color for the hour |
| `favorability_score` | float | Higher is better (see below) |
| `green_window_share` | float | 0–1 |
| `avg_pv_power_w`, `avg_battery_soc_percent`, `avg_load_w` | float | Hour averages |
| `expected_kwh` | float \| null | Avg session energy that hour |
| `reason` | string | Plain-language explanation |

### Billing ledger (`/billing`, `/accounts/{id}/billing`)
| Field | Type | Notes |
| --- | --- | --- |
| `ledger_id` | string | Primary key |
| `account_id` | string | |
| `event_type` | string | Top-up, cooking charge, reward, etc. |
| `session_id` | string \| null | FK → session when applicable |
| `credits_delta` | int | Signed |
| `cash_kes` | int | |
| `balance_after` | int | |
| `reason` | string | |
| `created_at` | string | ISO datetime |

### Credit balance (`/credit-balances`, `/accounts/{id}/credit-balance`)
| Field | Type | Notes |
| --- | --- | --- |
| `account_id`, `month` | string | Composite key |
| `account_type`, `entity_id` | string | |
| `ending_balance_credits` | int | |
| `total_top_up_credits`, `total_reward_credits`, `total_spent_credits` | int | |
| `cash_paid_kes` | int | |

### Leaderboard (`/leaderboard`)
| Field | Type | Notes |
| --- | --- | --- |
| `rank` | int | Primary key |
| `account_id`, `entity_id`, `account_type` | string | |
| `display_name` | string | Synthetic ID only (e.g. `Household HH-0007`) |
| `leaderboard_group` | string | `household` or `commercial` |
| `sessions` | int | |
| `kwh` | float | |
| `green_sessions`, `orange_sessions`, `red_sessions` | int | |
| `green_window_share` | float | |
| `shifted_daytime_sessions` | int | |
| `credits_earned`, `credits_spent`, `ending_balance_credits`, `cash_paid_kes` | int | |
| `fuel_stacking_risk_days` | int | |
| `score` | int | See dataset docs for formula |
| `privacy_level` | string | `synthetic_id_only` |

### Cooking plan (`/cooking-plans`) — runtime write resource
| Field | Type | Notes |
| --- | --- | --- |
| `plan_id` | string | Primary key (`PLAN-xxxxxxxx`) |
| `account_id` | string | FK → account |
| `cooker_id` | string \| null | Optional |
| `date` | string | `YYYY-MM-DD` |
| `start_hour_eat` | int | 0–23, chosen hour |
| `planned_duration_minutes` | float \| null | |
| `slot_color` | string | Assessed for the chosen hour |
| `expected_kwh` | float | |
| `suggested_credit_gain` | int | Credit-model output |
| `credit_gain_basis` | string | Human-readable explanation |
| `model_version` | string | `rules-v1` today (AI-ready) |
| `status` | string | `planned` / `confirmed` / `cancelled` |
| `created_at` | string | ISO datetime |

### Household persona (`/households`)
| Field | Type | Notes |
| --- | --- | --- |
| `household_id` | string | Primary key |
| `head_person_id` | string | FK → person |
| `occupants`, `children_count`, `meal_count_per_day` | int | |
| `income_band_kes_month` | string | |
| `breakfast_window`, `lunch_window`, `dinner_window` | string | |
| `primary_equipment`, `secondary_equipment`, `fuel_stack` | string | |
| `current_fuel_cost_kes_week`, `fuel_collection_minutes_week`, `time_spent_cooking_minutes_day` | float | |
| `other_grid_uses`, `secondary_microeconomic_activity` | string | |
| `estimated_other_grid_kwh_week` | float | |
| `clean_cooking_readiness_score`, `shiftable_cooking_score` | float | |
| `fuel_stacking_risk` | string | |
| `is_minigrid_user` | string | |
| `meter_status` | string | |

### Commercial profile (`/commercial-profiles`)
| Field | Type | Notes |
| --- | --- | --- |
| `business_id` | string | Primary key |
| `business_type` | string | |
| `owner_person_id` | string | FK → person |
| `opening_time`, `closing_time` | string | |
| `customers_avg_week` | int | |
| `primary_equipment`, `secondary_equipment`, `fuel_stack` | string | |
| `fuel_cost_kes_week`, `cooking_hours_day`, `estimated_cooking_kwh_week` | float | |
| `peak_prep_windows` | string | |
| `is_minigrid_user`, `meter_status` | string | |
| `clean_cooking_readiness_score`, `daytime_shift_potential` | float | |

### Person (`/people`, `/households/{id}/people`)
| Field | Type | Notes |
| --- | --- | --- |
| `person_id` | string | Primary key |
| `household_id` | string | FK → household |
| `age_band`, `gender`, `role` | string | |
| `student_or_worker_status`, `primary_activity` | string | |

## Recommendation logic

`scoring.py` aggregates the 720 hourly grid rows into one summary per hour of
day and scores each hour:

```
score = 60 * green_window_share
      + 25 * (avg_pv_power / peak_pv_power)
      + 15 * (avg_battery_soc / 100)
      - 20 * (avg_load / peak_load)
```

Each window returns its dominant `slot_color`, the score, expected kWh, and a
plain-language reason. This is the explainable MVP baseline described in
`docs/oloika_data_schema_and_prediction_notes.md`; a trained model can replace
the scoring function later without changing the API surface.

## Credit-gain model (AI-ready schema)

When a user books a cooking time, `POST /api/v1/cooking-plans` returns a
`suggested_credit_gain` plus `credit_gain_basis` and `model_version`. These
three fields are the stable contract. Today they are filled by a transparent
rules baseline; swapping in a trained AI model later requires no API change.

```
multiplier      = { green: 1.0, orange: 0.5, red: 0.0 }[slot_color]
energy_credits  = expected_kwh * 10 * multiplier
shift_bonus     = 8 if hour in 10:00-15:00 and slot_color != red else 0
suggested_credit_gain = round(energy_credits) + shift_bonus
```

Example: an 11:00 green window at ~1.06 kWh → `1.06 * 10 * 1.0 + 8 = 19` credits.
A 20:00 red window → `0` credits.

## Example responses

`examples/` contains a real JSON response for every endpoint (regenerated by the
script below), e.g. `examples/cooking_plan_created.json`,
`examples/account_recommendation.json`, `examples/leaderboard.json`.

## Postman mock server

`postman/gridcook_api.postman_collection.json` is a Postman v2.1 collection with
an example response saved on every request, so it can drive a **mock server**
with no backend running.

1. Postman → Import → select the collection file.
2. Collections → GridCook Oloika API → ⋯ → **Mock collection**.
3. Set the `baseUrl` collection variable to the generated mock URL.

To point the collection at a live local server instead, set `baseUrl` to
`http://127.0.0.1:8000`.

### Regenerating examples and the collection

```bash
uvicorn gridcook.main:app --port 8000        # terminal 1
python3 scripts/build_api_examples.py --base-url http://127.0.0.1:8000  # terminal 2
```
