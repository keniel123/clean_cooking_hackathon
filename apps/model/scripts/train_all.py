"""Train the full model suite on the historical month and save checkpoints.

Uses a temporal split (train on the early part of June, test on later days) and
compares every model against a transparent baseline. Run from apps/model:

    python3 scripts/train_all.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import torch
from torch import nn

from gridcook_model.data import features
from gridcook_model.data.dataset import Standardizer, make_loader, temporal_mask, to_tensor
from gridcook_model.models import DemandForecaster, GridForecaster, Recommender, RiskClassifier
from gridcook_model.registry import checkpoints_dir, save_checkpoint
from gridcook_model.training import evaluate, trainer

DEFAULT_CUTOFF = "2025-06-23"
LOOKBACK = 48
HORIZON = 24


def train_forecaster(epochs: int) -> dict:
    inputs, outputs = features.build_grid_sequences(LOOKBACK, HORIZON)
    num_features = inputs.shape[-1]
    num_targets = outputs.shape[-1]
    split = int(len(inputs) * 0.8)

    feature_scaler = Standardizer.fit(inputs[:split].reshape(-1, num_features))
    target_scaler = Standardizer.fit(outputs[:split].reshape(-1, num_targets))

    def scale(matrix: np.ndarray, scaler: Standardizer, width: int) -> np.ndarray:
        return scaler.transform(matrix.reshape(-1, width)).reshape(matrix.shape)

    train_x = scale(inputs[:split], feature_scaler, num_features)
    test_x = scale(inputs[split:], feature_scaler, num_features)
    train_y = scale(outputs[:split], target_scaler, num_targets)
    test_y = scale(outputs[split:], target_scaler, num_targets)

    model = GridForecaster(num_features=num_features, num_targets=num_targets, horizon=HORIZON)
    loader = make_loader(to_tensor(train_x), to_tensor(train_y), batch_size=32, shuffle=True)

    def loss_fn(module: nn.Module, batch: tuple[torch.Tensor, ...]) -> torch.Tensor:
        sequence, target = batch
        return nn.functional.mse_loss(module(sequence), target)

    trainer.train(model, loader, loss_fn, epochs=epochs)
    model.eval()
    with torch.no_grad():
        predictions = model(to_tensor(test_x)).numpy()

    model_mae = evaluate.mae(predictions, test_y)
    baseline_mae = evaluate.mae(np.zeros_like(test_y), test_y)  # mean (standardized) baseline
    metrics = {
        "test_mae_standardized": round(model_mae, 4),
        "baseline_mean_mae_standardized": round(baseline_mae, 4),
        "test_samples": int(len(test_x)),
    }
    save_checkpoint("grid_forecaster", model, {
        "standardizer": feature_scaler.to_dict(),
        "target_standardizer": target_scaler.to_dict(),
        "feature_columns": features.GRID_FEATURE_COLUMNS,
        "target_columns": features.FORECAST_TARGET_COLUMNS,
        "lookback": LOOKBACK,
        "horizon": HORIZON,
        "metrics": metrics,
    })
    return metrics


def train_risk(cutoff: str, epochs: int) -> dict:
    inputs, labels, dates = features.build_risk_dataset()
    train_mask, test_mask = temporal_mask(dates, cutoff)
    scaler = Standardizer.fit(inputs[train_mask])

    model = RiskClassifier(num_features=inputs.shape[1])
    loader = make_loader(
        to_tensor(scaler.transform(inputs[train_mask])),
        to_tensor(labels[train_mask], dtype=torch.long),
        batch_size=64, shuffle=True,
    )

    def loss_fn(module: nn.Module, batch: tuple[torch.Tensor, ...]) -> torch.Tensor:
        grid, target = batch
        return nn.functional.cross_entropy(module(grid), target)

    trainer.train(model, loader, loss_fn, epochs=epochs)
    model.eval()
    with torch.no_grad():
        predicted = model(to_tensor(scaler.transform(inputs[test_mask]))).argmax(1).numpy()

    baseline = evaluate.majority_class_baseline(labels[train_mask], int(test_mask.sum()))
    metrics = {
        "test_macro_f1": round(evaluate.macro_f1(predicted, labels[test_mask]), 4),
        "baseline_macro_f1": round(evaluate.macro_f1(baseline, labels[test_mask]), 4),
        "confusion_matrix": evaluate.confusion_matrix(predicted, labels[test_mask]).tolist(),
        "test_samples": int(test_mask.sum()),
    }
    save_checkpoint("risk_classifier", model, {
        "standardizer": scaler.to_dict(),
        "feature_columns": features.GRID_FEATURE_COLUMNS,
        "metrics": metrics,
    })
    return metrics


def train_demand(cutoff: str, epochs: int) -> dict:
    inputs, targets, dates, hours = features.build_demand_dataset()
    train_mask, test_mask = temporal_mask(dates, cutoff)
    scaler = Standardizer.fit(inputs[train_mask])

    model = DemandForecaster(num_features=inputs.shape[1])
    loader = make_loader(
        to_tensor(scaler.transform(inputs[train_mask])),
        to_tensor(targets[train_mask]),
        batch_size=64, shuffle=True,
    )

    def loss_fn(module: nn.Module, batch: tuple[torch.Tensor, ...]) -> torch.Tensor:
        grid, target = batch
        return nn.functional.mse_loss(module(grid), target)

    trainer.train(model, loader, loss_fn, epochs=epochs)
    model.eval()
    with torch.no_grad():
        predictions = model(to_tensor(scaler.transform(inputs[test_mask]))).numpy()

    baseline = evaluate.hour_of_day_baseline(hours[train_mask], targets[train_mask], hours[test_mask])
    metrics = {
        "test_mae": round(evaluate.mae(predictions, targets[test_mask]), 4),
        "baseline_hour_of_day_mae": round(evaluate.mae(baseline, targets[test_mask]), 4),
        "test_samples": int(test_mask.sum()),
    }
    save_checkpoint("demand_forecaster", model, {
        "standardizer": scaler.to_dict(),
        "feature_columns": features.GRID_FEATURE_COLUMNS,
        "target_columns": ["sessions", "kwh"],
        "metrics": metrics,
    })
    return metrics


def train_recommender(cutoff: str, epochs: int) -> dict:
    inputs, slot, kwh, dates, columns = features.build_recommender_dataset()
    train_mask, test_mask = temporal_mask(dates, cutoff)
    scaler = Standardizer.fit(inputs[train_mask])
    train_x = scaler.transform(inputs[train_mask])

    model = Recommender(num_features=inputs.shape[1])
    loader = make_loader(
        to_tensor(train_x),
        to_tensor(slot[train_mask], dtype=torch.long),
        to_tensor(kwh[train_mask]),
        batch_size=64, shuffle=True,
    )

    def loss_fn(module: nn.Module, batch: tuple[torch.Tensor, ...]) -> torch.Tensor:
        grid, slot_target, kwh_target = batch
        slot_logits, kwh_pred = module(grid)
        return nn.functional.cross_entropy(slot_logits, slot_target) \
            + nn.functional.mse_loss(kwh_pred, kwh_target)

    trainer.train(model, loader, loss_fn, epochs=epochs)
    model.eval()
    with torch.no_grad():
        slot_logits, kwh_pred = model(to_tensor(scaler.transform(inputs[test_mask])))
    predicted_slot = slot_logits.argmax(1).numpy()

    baseline = evaluate.majority_class_baseline(slot[train_mask], int(test_mask.sum()))
    metrics = {
        "test_slot_macro_f1": round(evaluate.macro_f1(predicted_slot, slot[test_mask]), 4),
        "baseline_slot_macro_f1": round(evaluate.macro_f1(baseline, slot[test_mask]), 4),
        "test_kwh_mae": round(evaluate.mae(kwh_pred.numpy(), kwh[test_mask]), 4),
        "test_samples": int(test_mask.sum()),
    }
    save_checkpoint("recommender", model, {
        "standardizer": scaler.to_dict(),
        "feature_columns": columns,
        "metrics": metrics,
    })

    seed_path = checkpoints_dir() / "recommender" / "replay_seed.npz"
    np.savez(seed_path, features=train_x, slot=slot[train_mask], kwh=kwh[train_mask])
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cutoff", default=DEFAULT_CUTOFF, help="Last training date (inclusive)")
    parser.add_argument("--epochs", type=int, default=60)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)

    summary = {
        "grid_forecaster": train_forecaster(args.epochs),
        "risk_classifier": train_risk(args.cutoff, args.epochs),
        "demand_forecaster": train_demand(args.cutoff, args.epochs),
        "recommender": train_recommender(args.cutoff, args.epochs),
    }
    print(json.dumps(summary, indent=2))
    print(f"\nCheckpoints written to {checkpoints_dir()}")


if __name__ == "__main__":
    main()
