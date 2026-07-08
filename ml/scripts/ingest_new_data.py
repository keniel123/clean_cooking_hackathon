"""Continual-learning update: fine-tune the recommender on a new batch of data.

Demonstrates the replay-based loop from the README. It treats the days after
``--cutoff`` as "newly arrived" data, fine-tunes a copy of the current model on
that batch mixed with a replay sample of history, validates against the current
model and a baseline, and promotes a new checkpoint version only if it wins.

    python3 scripts/ingest_new_data.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import torch

from gridcook_model.data import features
from gridcook_model.data.dataset import Standardizer, temporal_mask, to_tensor
from gridcook_model.data.replay import ReplayBuffer
from gridcook_model.models import Recommender
from gridcook_model.registry import checkpoints_dir, latest_version, load_checkpoint, save_checkpoint
from gridcook_model.training import evaluate
from gridcook_model.training.continual import build_finetune_arrays, promote_if_better, replay_finetune

DEFAULT_CUTOFF = "2025-06-23"
REPLAY_CAPACITY = 2000
REPLAY_SAMPLE = 512
MIN_NEW_SAMPLES = {"cutoff": 10, "live": 5}


def _slot_macro_f1(model: Recommender, feature_matrix: np.ndarray, slot: np.ndarray) -> float:
    model.eval()
    with torch.no_grad():
        slot_logits, _ = model(to_tensor(feature_matrix))
    return evaluate.macro_f1(slot_logits.argmax(1).numpy(), slot)


def _build_live_batch(scaler: Standardizer) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    """New training rows built straight from API-recorded live sessions.

    Each live session -> the same (account + grid-hour) feature row the model was
    trained on, labelled with the session's observed slot color and kWh.
    """
    live = features.load_live_sessions()
    if live.empty:
        return None
    rows: list[np.ndarray] = []
    slots: list[int] = []
    kwhs: list[list[float]] = []
    for _, record in live.iterrows():
        account_id = str(record["account_id"])
        hour = int(record["start_hour_eat"])
        feature_row = features.account_grid_feature_row(account_id, hour)
        if feature_row is None:
            continue
        rows.append(feature_row[0])
        slots.append(features.SLOT_TO_INDEX[str(record["slot_color"])])
        kwhs.append([float(record["kwh"])])
    if not rows:
        return None
    feature_matrix = scaler.transform(np.asarray(rows, dtype=np.float32))
    return feature_matrix, np.asarray(slots, dtype=np.int64), np.asarray(kwhs, dtype=np.float32)


def _loss_fn(module, batch):
    grid, slot_target, kwh_target = batch
    slot_logits, kwh_pred = module(grid)
    return torch.nn.functional.cross_entropy(slot_logits, slot_target) \
        + torch.nn.functional.mse_loss(kwh_pred, kwh_target)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=["cutoff", "live"], default="cutoff",
                        help="'live': learn from API-recorded sessions; 'cutoff': simulate from history")
    parser.add_argument("--cutoff", default=DEFAULT_CUTOFF, help="Boundary between history and new data")
    parser.add_argument("--epochs", type=int, default=15)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    if latest_version("recommender") is None:
        raise SystemExit("No recommender checkpoint found. Run scripts/train_all.py first.")

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)

    current, metadata = load_checkpoint("recommender", Recommender)
    scaler = Standardizer.from_dict(metadata["standardizer"])

    if args.source == "live":
        live_batch = _build_live_batch(scaler)
        if live_batch is None:
            raise SystemExit("No live sessions to learn from. Record sessions via the API first.")
        new_x, new_slot, new_kwh = live_batch
    else:
        inputs, slot, kwh, dates, _ = features.build_recommender_dataset()
        _, new_mask = temporal_mask(dates, args.cutoff)
        new_x = scaler.transform(inputs[new_mask])
        new_slot = slot[new_mask]
        new_kwh = kwh[new_mask]

    if len(new_x) < MIN_NEW_SAMPLES[args.source]:
        raise SystemExit(
            f"Not enough new '{args.source}' data ({len(new_x)}) to run a continual update."
        )

    # Split the new batch: fine-tune on part, validate on the held-out remainder.
    split = int(len(new_x) * 0.7)
    finetune_arrays = [new_x[:split], new_slot[:split], new_kwh[:split]]
    val_x, val_slot = new_x[split:], new_slot[split:]

    # Rebuild the replay buffer from the seed saved at training time.
    buffer = ReplayBuffer(capacity=REPLAY_CAPACITY, seed=args.seed)
    seed_path = checkpoints_dir() / "recommender" / "replay_seed.npz"
    if seed_path.exists():
        seed = np.load(seed_path)
        buffer.add(seed["features"], seed["slot"], seed["kwh"])

    mixed = build_finetune_arrays(finetune_arrays, buffer, REPLAY_SAMPLE)
    tensors = (
        to_tensor(mixed[0]),
        to_tensor(mixed[1], dtype=torch.long),
        to_tensor(mixed[2]),
    )
    candidate, _ = replay_finetune(candidate_source(current), tensors, _loss_fn, epochs=args.epochs)

    current_f1 = _slot_macro_f1(current, val_x, val_slot)
    candidate_f1 = _slot_macro_f1(candidate, val_x, val_slot)
    baseline = evaluate.majority_class_baseline(new_slot[:split], len(val_slot))
    baseline_f1 = evaluate.macro_f1(baseline, val_slot)

    promote = promote_if_better(candidate_f1, current_f1, baseline_f1, higher_is_better=True)
    decision = {
        "source": args.source,
        "current_val_macro_f1": round(current_f1, 4),
        "candidate_val_macro_f1": round(candidate_f1, 4),
        "baseline_val_macro_f1": round(baseline_f1, 4),
        "promoted": promote,
        "new_samples": int(len(new_x)),
    }

    if promote:
        new_metadata = dict(metadata)
        new_metadata["metrics"] = {**metadata.get("metrics", {}),
                                   "continual_val_macro_f1": round(candidate_f1, 4)}
        version = save_checkpoint("recommender", candidate, new_metadata)
        decision["new_version"] = version
        # Grow the replay buffer with the newly ingested batch for next time.
        buffer.add(new_x, new_slot, new_kwh)
        np.savez(seed_path, features=mixed[0], slot=mixed[1], kwh=mixed[2])

    print(json.dumps(decision, indent=2))


def candidate_source(model: Recommender) -> Recommender:
    """Return the model to warm-start from (kept as a hook for clarity)."""
    return model


if __name__ == "__main__":
    main()
