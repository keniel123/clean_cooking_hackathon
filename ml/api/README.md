# GridCook ML Serving API

This API is intentionally small. It is the clean model-facing API for demos and integration.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | API health plus active model version |
| `GET` | `/model/status` | Export status, checkpoint audit, metrics |
| `GET` | `/accounts/{account_id}/profile` | Account wallet, behavior, cookers, leaderboard row |
| `GET` | `/accounts/{account_id}/recommendations?top=24` | Personalized 24-hour model recommendations |
| `GET` | `/recommendations/hourly` | Community (grid-level) per-hour recommendation |
| `POST` | `/plans` | Score a selected cooking time |
| `GET` | `/leaderboard` | Demo leaderboard |
| `POST` | `/learning/continual-update?source=live` | Retrain from funneled live sessions, then hot-reload |

## Continual learning (closed loop)

The product API (`apps/api`) records real cooking sessions and appends them to
`data/runtime/live_sessions.csv`. When `POST /learning/continual-update?source=live`
runs, [ml/scripts/ingest_new_data.py](../scripts/ingest_new_data.py) builds a new
training batch straight from those live rows (via
`features.load_sessions()` / `features.account_grid_feature_row`), replay-fine-tunes
the recommender, and promotes a new `nn-vN` checkpoint only if it beats the current
one. The endpoint then calls `model_store.reload()` so the running service serves
the new version immediately - no restart. Set `source=cutoff` to instead simulate
new data from history.

## Run Locally

```bash
uvicorn ml.api.main:app --reload --port 8100
```

Enable continual-learning updates through the API only for demos:

```bash
GRIDCOOK_ENABLE_CONTINUAL_LEARNING=1 uvicorn ml.api.main:app --reload --port 8100
```

## Example

```bash
curl http://127.0.0.1:8100/accounts/HH-0007/recommendations?top=24
```
