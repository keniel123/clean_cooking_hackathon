# GridCook ML Workspace

This folder is the single source of truth for all model work. It holds the
model/training/serving code (`gridcook_model/`), the training environment
(`.venv/`), the training/export/audit scripts (`scripts/`), the trained
checkpoints (`checkpoints/`), the active API-serving export (`exports/`), audit
reports (`reports/`), and a small clean ML-serving API (`api/`).

## Models

Trained checkpoint status:

| Module file | Model | Checkpoint status | Use in demo |
| --- | --- | --- | --- |
| `grid_forecaster.py` | Grid/solar forecaster | trained | supporting |
| `risk_classifier.py` | Grid-risk classifier | trained | yes |
| `demand_forecaster.py` | Cooking demand forecaster | trained | experimental |
| `recommender.py` | Account recommender / credit model | trained | yes |

The important demo model is the recommender. It produces personalized 24-hour
predictions for each account:

- `slot_color`
- `expected_kwh`
- `suggested_credit_gain`
- `credit_gain_basis`
- `model_version`

All commands use the workspace virtualenv (`ml/.venv`). Run them from the repo root.

## Commands

Train all models, export the recommender, and write the audit report:

```bash
ml/.venv/bin/python ml/scripts/run_training_pipeline.py --epochs 60
```

Run a model audit only:

```bash
ml/.venv/bin/python ml/scripts/audit_models.py
```

Run a continual-learning update (fine-tune on new data, promote if it wins):

```bash
ml/.venv/bin/python ml/scripts/run_continual_update.py --cutoff 2025-06-23 --epochs 15
```

Export the recommender for the API/app only:

```bash
ml/.venv/bin/python ml/scripts/export_predictions.py
```

Run the clean ML API (from `ml/`):

```bash
cd ml && .venv/bin/python -m uvicorn api.main:app --reload --port 8100
```

Container build:

```bash
docker build -f ml/Dockerfile -t gridcook-ml .
docker run --rm -p 8100:8100 gridcook-ml
```

## Layout and data flow

```text
ml/
  .venv/            # training environment (torch/numpy/pandas/scikit-learn + fastapi/uvicorn)
  requirements.txt  # training dependencies
  gridcook_model/   # THE model/training/serving package
  scripts/          # train_all, export_for_api, ingest_new_data + wrappers
  checkpoints/      # trained checkpoints (registry default)
  exports/          # active API-serving export (nn_predictions.json)
  reports/          # audit and metrics reports
  api/              # small clean model-serving API
```

```text
data/synthetic CSVs
  -> ml/scripts/train_all.py       -> ml/checkpoints
  -> ml/scripts/export_for_api.py  -> ml/exports/nn_predictions.json
  -> ml/scripts/audit_models.py    -> ml/reports/model_audit.json
  -> ml/api (inference)  and  apps/gateway (reads ml/exports/nn_predictions.json)
```

Training reads `data/synthetic`, writes checkpoints to `ml/checkpoints`, exports the
serving artifact to `ml/exports/nn_predictions.json`, and writes the audit to
`ml/reports/model_audit.json`. Both `ml/api` and the `apps/gateway` fallback read the
same `ml/exports/nn_predictions.json`; if it is missing they fall back to rules-based logic.

## Data Position

Do not generate a large fake dataset just to look bigger.

For the hackathon, the proper scope is:

- Use the real downloaded June 2025 Oloika grid and smart-plug data.
- Use transparent synthetic personas and synthetic fill for accounts without observed plug data.
- Use one month as the honest historical training month.
- Use the continual-learning script to demonstrate how the model updates when new sessions arrive.

If we need more data for a stronger demo later, generate one or two additional synthetic months only as a clearly labeled stress test, not as real evidence.

## Recommended Demo Story

```text
We trained a small recommender and risk model on the linked Oloika dataset. The model export contains personalized 24-hour recommendations for every mini-grid account, and the API consumes that export without running PyTorch at request time. When new grid and cooking data arrives, we fine-tune the recommender with replay and only promote a new version if it beats the current model and baseline.
```

## What Is Shippable Now

Shippable for hackathon:

- model training scripts
- checkpoint registry
- metrics and baselines
- personalized export artifact
- API integration
- continual-learning demo loop
- documentation of limitations

Not production-ready yet:

- only one real month of telemetry
- limited observed smart-plug users
- synthetic personas and billing
- no weather forecast input yet
- demand forecaster underperforms baseline
