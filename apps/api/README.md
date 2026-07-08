# GridCook Oloika API

A lightweight REST API over the Oloika June 2025 dataset (`data/synthetic/`).
On first startup it seeds the documented CSV/JSON files into a **file-backed**
SQLite database (`data/runtime/gridcook.db`); durable runtime tables (bookings,
live sessions, training counter) then persist across restarts. Recommendations
come from the live ML model (`ml/api`) with a rules baseline fallback, and are
**coordinated against the shared grid's live capacity** so users are steered
away from hours the rest of the community has already committed to.

This is one shared mini-grid with many users: every recorded session funnels
back into the model so the next user's recommendations reflect the whole
community's latest usage. See "Shared-grid capacity + continual learning" below.

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
| GET | `/api/v1/accounts/{account_id}/credit-balance` | End-of-month credit balance (historical dataset) |
| GET | `/api/v1/accounts/{account_id}/wallet` | Live earned-credit wallet (accrues from sessions) |
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
| GET | `/api/v1/grid/daily-plan` | Per hour-of-day plan with live capacity overlay (`date`) |
| GET | `/api/v1/grid/capacity` | Per-hour capacity, committed load, headroom (`date`) |
| GET | `/api/v1/recommendations` | Top grid-level windows, capacity-adjusted (`top`, `date`) |

The `/accounts/{id}/recommendation` and the three endpoints above accept an
optional `date` (defaults to today). Committed load from `cooking_plans` and
`cooking_sessions_live` for that date reduces headroom, downgrades busy hours,
and re-ranks windows so the shared grid is not overloaded.

### Live sessions & learning (write)
| Method | Path | Description |
| --- | --- | --- |
| POST | `/api/v1/sessions` | Record an actual cooking session; funnels into ML training |
| GET | `/api/v1/learning/state` | Sessions since last retrain, last trained version |
| POST | `/api/v1/learning/retrain` | Manually trigger a continual-learning update |

`POST /api/v1/sessions` persists the session, appends it to
`data/runtime/live_sessions.csv`, and increments the training counter. After
`GRIDCOOK_RETRAIN_EVERY` (default 20) sessions it fires a background retrain.

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
  "suggested_credit_gain": 0.15,
  "credit_gain_basis": "green session +0.1 +0.05 daytime-shift",
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

## Credit-gain model (smart, model-derived + accumulating)

Credits are small fractional rewards that **accumulate**, and the amount is
**intelligent** - driven by the learned recommender, not a flat rate. Only green
windows earn anything (orange/red earn nothing), and a single session never
grants a whole credit: users accrue fractions and realize a whole credit once
their running total crosses `1.0`.

```
reward = BASE(0.2)
       x P(green)          # model's confidence this hour is genuinely good (learned)
       x grid_benefit      # solar surplus / low grid stress at the hour (learned)
       x (1 + 0.5*shift)   # personalization: shift = 1 - account's green_window_share
       x scarcity          # live capacity: more headroom -> more credit
   0 for orange/red, capped at 1.0 per session
```

Every factor is model/data-driven, so rewards adapt each time continual learning
retrains on new community data: a strongly green, high-solar, underused hour for
a user with bad habits pays far more than a barely green one, and a user who
already always cooks green earns a smaller shift bonus. When the ML service is
down, `scoring.py` falls back to the same shape using hourly aggregates
(green-share x grid-benefit).

When a real session is recorded via `POST /api/v1/sessions`, the reward is added
to the account wallet (`credit_wallet`): `accumulated_credit` grows and
`credits_awarded` (its floor) ticks up a whole credit each time the total
crosses an integer. Read progress at `GET /api/v1/accounts/{id}/wallet`.

Because capacity coordination can downgrade a busy green hour to orange/red, a
window that fills up drops to `0` credit - the reward follows the final
(capacity-adjusted) color, and green rewards shrink as headroom shrinks.

## Shared-grid capacity + continual learning

This is one shared mini-grid. Two mechanisms keep recommendations honest:

1. **Live capacity overlay** (`capacity.py`): per-hour usable capacity is derived
   from historical PV/battery availability; committed load (bookings + live
   sessions for the date) is subtracted to get headroom. Hours above 60%
   utilisation are downgraded a color, hours at/above 85% (or the concurrent
   cooker cap) are marked full (red) with zero credit, and windows are re-ranked
   toward headroom. So if others book 12:00, the next user is steered elsewhere.

2. **Closed learning loop**: `POST /api/v1/sessions` records real usage and
   appends it to `data/runtime/live_sessions.csv`. The ML trainer
   (`features.load_sessions()`) concatenates those rows onto the June history, so
   retraining learns from the full community. After `GRIDCOOK_RETRAIN_EVERY`
   sessions, the API calls `ml/api` `POST /learning/continual-update?source=live`,
   which fine-tunes, promotes a new `nn-vN` checkpoint if it wins, and hot-reloads
   the live model. The next recommendation reflects the newest community data.

```
user cooks -> POST /sessions -> gridcook.db + live_sessions.csv -> (every N)
   -> ml/api retrain -> promote nn-vN -> hot-reload -> next user's recs updated
```

### Configuration
| Env var | Default | Purpose |
| --- | --- | --- |
| `GRIDCOOK_DB_PATH` | `data/runtime/gridcook.db` | File-backed SQLite location |
| `GRIDCOOK_LIVE_SESSIONS` | `data/runtime/live_sessions.csv` | Live-session training bridge |
| `GRIDCOOK_RETRAIN_EVERY` | `20` | Sessions between automatic retrains |
| `GRIDCOOK_ML_API_URL` | `http://127.0.0.1:8100` | ML serving API base URL |
| `GRIDCOOK_GRID_CAPACITY_KWH` | `12.0` | Base shared-grid cooking capacity per hour |
| `GRIDCOOK_MAX_CONCURRENT_COOKERS` | `8` | Hard cap on concurrent cookers per hour |

Automatic retrain requires `ml/api` to run with
`GRIDCOOK_ENABLE_CONTINUAL_LEARNING=1`.

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
