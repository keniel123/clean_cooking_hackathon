# How the GridCook ML works

A short tour of the model, the endpoints, and how reward + continual learning fit
together. Two services:

- **`ml/api`** (port `8132`) — the model. Torch lives here. Live inference only.
- **`apps/api`** (port `8092`) — the product API clients talk to. Torch-free; it
  calls `ml/api` over HTTP and overlays live shared-grid capacity.

```
client -> apps/api (8092) -> ml/api (8132)  [P(green), expected_kWh, smart reward]
                          -> capacity.py     [live grid headroom -> recolor/re-rank]
                          -> SQLite          [sessions, wallet, live_sessions.csv]
          (if ml/api is down, apps/api falls back to rules in scoring.py)
```

---

## The model

The recommender is a small neural net. For a `(account, hour)` pair it takes:

- **Account features** — that account's historical behavior (sessions, kWh,
  green-window share, credits, fuel-stacking risk) + persona (household /
  commercial readiness, shiftability).
- **Grid features** — the community grid's mean state for that hour of day (solar
  power, battery SoC, load, voltage, alarms, cyclical hour).

and predicts two things:

1. **Slot suitability** — a softmax over `green / orange / red` (how good this hour
   is for the shared grid). We use both the argmax color and `P(green)`.
2. **Expected kWh** — how much energy the session likely draws.

Because the grid features are shared across all users, the model reasons about
**one shared mini-grid with many users**, not isolated accounts. It's genuine live
inference — a fresh forward pass per request, not a lookup table.

There are also supporting models (grid/solar forecaster, demand forecaster, risk
classifier) but the recommender is what drives the product.

---

## Recommendation

When a user signs in, the app calls **`GET /api/v1/accounts/{id}/recommendation`**.
Pipeline:

1. `apps/api` asks `ml/api` for the account's full 24-hour set (per-hour color,
   expected kWh, smart reward).
2. `capacity.py` overlays the **live** shared grid for that date: it computes
   per-hour usable capacity (scaled by historical solar/battery availability) and
   subtracts **committed load** (other users' bookings + live sessions). Hours
   over 60% utilisation are downgraded a color; hours at/above 85% (or the
   concurrent-cooker cap) become red/full with zero credit.
3. Windows are re-ranked toward headroom and returned as `recommended_windows`
   (top-N) + `all_windows` (the 24h timeline).

So if others pile onto 12:00, the next user is steered to a still-green hour. Every
response carries `model_version` (e.g. `nn-v5`) — if it reads `rules-v1`, the ML
service was down and the rules fallback answered.

---

## Reward (smart, model-derived, accumulating)

Only **green** windows earn credit. Among green hours the amount is continuous and
driven by the model, not a flat rate:

```
reward = BASE(0.2)
       x P(green)          # model confidence this hour is genuinely good
       x grid_benefit      # solar surplus / low grid stress at the hour (learned)
       x (1 + 0.5*shift)   # personalization: shift = 1 - account's green_window_share
       x scarcity          # live capacity: more headroom -> more credit
   0 for orange/red, capped at 1.0 per session
```

- A **strongly green, high-solar, underused** hour pays far more than a barely
  green one; a user with **bad habits** earns more for shifting than one who
  already always cooks green.
- Credits **accumulate**: `POST /api/v1/sessions` adds the fraction to the
  account's `credit_wallet`; a **whole credit** is awarded only when the running
  total crosses `1.0`. Check progress at `GET /api/v1/accounts/{id}/wallet`.
- All factors come from learned/data signals, so rewards **adapt automatically**
  every time the model retrains.

---

## Continual learning (closed loop)

The grid is shared, so new usage should make the next user's recommendations
smarter. That loop is closed:

1. `POST /api/v1/sessions` records real usage in `gridcook.db` and appends it to
   `data/runtime/live_sessions.csv` (same schema as history).
2. The trainer concatenates those live rows onto the June history, so it learns
   from the **full community**.
3. After `GRIDCOOK_RETRAIN_EVERY` sessions the API **automatically** kicks a
   retrain (no manual endpoint). It is a **replay-based incremental fine-tune**,
   not from scratch: warm-start from the current checkpoint, mix new sessions with
   a replay sample of history (so it doesn't forget), and **promote a new
   `nn-vN` checkpoint only if it beats the current model + a baseline**.
4. The retrain runs **asynchronously in-process** on `ml/api` (single-flight
   background thread). `POST /sessions` returns instantly, inference keeps serving
   the current model, and the model **hot-swaps** only on promotion.

```
user cooks -> POST /sessions -> gridcook.db + live_sessions.csv -> (every N)
   -> ml/api background fine-tune -> promote nn-vN if better -> hot-swap -> next recs updated
```

---

## Endpoints

### `ml/api` (internal model service, :8132)
| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Status + live model version |
| GET | `/model/status` | Model version, community-hours count, audit |
| GET | `/accounts/{id}/recommendations` | Live per-account 24h windows (ranked) |
| GET | `/recommendations/hourly` | Community per-hour view (account-averaged) |
| POST | `/plans` | Score one chosen `(account, hour)` |
| GET | `/accounts/{id}/profile` | Account profile used by the model |
| GET | `/leaderboard` | Credit leaderboard |
| POST | `/learning/continual-update` | Kick async retrain (202); needs `GRIDCOOK_ENABLE_CONTINUAL_LEARNING=1` |
| GET | `/learning/status` | Retrain job state + live model version |

### `apps/api` (product API, :8092)
| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/v1/accounts/{id}/recommendation` | **Sign-in call**: personalized, capacity-aware 24h windows + credits |
| GET | `/api/v1/grid/daily-plan` | Community 24h color-coded plan |
| GET | `/api/v1/grid/capacity` | Live per-hour capacity / headroom |
| POST | `/api/v1/cooking-plans` | Book a chosen time; returns `suggested_credit_gain` |
| POST | `/api/v1/sessions` | Record real usage -> wallet + funnels to ML (auto-kicks retrain) |
| GET | `/api/v1/accounts/{id}/wallet` | Accumulated fraction + whole credits awarded |
| GET | `/api/v1/learning/state` | Sessions since retrain, last version, live retrain status |

---

## Run it

```bash
# ML service (from repo root)
PYTHONPATH="$PWD/ml" GRIDCOOK_ENABLE_CONTINUAL_LEARNING=1 \
  ml/.venv/bin/python -m uvicorn ml.api.main:app --port 8132

# Product API
cd apps/api && PYTHONPATH="$PWD" GRIDCOOK_ML_API_URL="http://127.0.0.1:8132" \
  .venv/bin/python -m uvicorn gridcook.main:app --port 8092
```

Docs: http://127.0.0.1:8092/docs (product) and http://127.0.0.1:8132/docs (model).
