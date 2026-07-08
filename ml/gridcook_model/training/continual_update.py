"""In-process replay-based continual update for the recommender.

This is the importable core the ML serving API calls on a background thread. It
warm-starts from the current checkpoint, fine-tunes on the newly funneled batch
mixed with a replay sample of history, validates on held-out new data, and
promotes a new checkpoint version only if it beats the current model + baseline.

Kept free of argparse / process spawning so it can run inside the live service
without a cold Python + torch start (see ``ml/api/retrain.py``). The thin CLI in
``scripts/ingest_new_data.py`` wraps ``run_update`` for offline use.
"""

from __future__ import annotations

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
    """New training rows built straight from API-recorded live sessions."""
    live = features.load_live_sessions()
    if live.empty:
        return None
    rows: list[np.ndarray] = []
    slots: list[int] = []
    kwhs: list[list[float]] = []
    for _, record in live.iterrows():
        feature_row = features.account_grid_feature_row(
            str(record["account_id"]), int(record["start_hour_eat"])
        )
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


def run_update(source: str = "live", cutoff: str = DEFAULT_CUTOFF,
               epochs: int = 5, seed: int = 7) -> dict:
    """Run one continual update. Returns a decision dict; never raises for the
    normal "not enough new data" case (returns ``promoted=False, skipped=True``)."""
    if latest_version("recommender") is None:
        raise RuntimeError("No recommender checkpoint found. Run scripts/train_all.py first.")

    torch.manual_seed(seed)
    np.random.seed(seed)

    current, metadata = load_checkpoint("recommender", Recommender)
    scaler = Standardizer.from_dict(metadata["standardizer"])

    if source == "live":
        live_batch = _build_live_batch(scaler)
        if live_batch is None:
            return {"source": source, "promoted": False, "skipped": True,
                    "reason": "no live sessions to learn from"}
        new_x, new_slot, new_kwh = live_batch
    else:
        inputs, slot, kwh, dates, _ = features.build_recommender_dataset()
        _, new_mask = temporal_mask(dates, cutoff)
        new_x = scaler.transform(inputs[new_mask])
        new_slot = slot[new_mask]
        new_kwh = kwh[new_mask]

    if len(new_x) < MIN_NEW_SAMPLES[source]:
        return {"source": source, "promoted": False, "skipped": True,
                "reason": f"not enough new data ({len(new_x)} rows)", "new_samples": int(len(new_x))}

    split = int(len(new_x) * 0.7)
    finetune_arrays = [new_x[:split], new_slot[:split], new_kwh[:split]]
    val_x, val_slot = new_x[split:], new_slot[split:]

    buffer = ReplayBuffer(capacity=REPLAY_CAPACITY, seed=seed)
    seed_path = checkpoints_dir() / "recommender" / "replay_seed.npz"
    if seed_path.exists():
        replay_seed = np.load(seed_path)
        buffer.add(replay_seed["features"], replay_seed["slot"], replay_seed["kwh"])

    mixed = build_finetune_arrays(finetune_arrays, buffer, REPLAY_SAMPLE)
    tensors = (to_tensor(mixed[0]), to_tensor(mixed[1], dtype=torch.long), to_tensor(mixed[2]))
    candidate, _ = replay_finetune(current, tensors, _loss_fn, epochs=epochs)

    current_f1 = _slot_macro_f1(current, val_x, val_slot)
    candidate_f1 = _slot_macro_f1(candidate, val_x, val_slot)
    baseline = evaluate.majority_class_baseline(new_slot[:split], len(val_slot))
    baseline_f1 = evaluate.macro_f1(baseline, val_slot)

    promote = promote_if_better(candidate_f1, current_f1, baseline_f1, higher_is_better=True)
    decision = {
        "source": source,
        "current_val_macro_f1": round(current_f1, 4),
        "candidate_val_macro_f1": round(candidate_f1, 4),
        "baseline_val_macro_f1": round(baseline_f1, 4),
        "promoted": promote,
        "skipped": False,
        "new_samples": int(len(new_x)),
    }

    if promote:
        new_metadata = dict(metadata)
        new_metadata["metrics"] = {**metadata.get("metrics", {}),
                                   "continual_val_macro_f1": round(candidate_f1, 4)}
        decision["new_version"] = save_checkpoint("recommender", candidate, new_metadata)
        buffer.add(new_x, new_slot, new_kwh)
        np.savez(seed_path, features=mixed[0], slot=mixed[1], kwh=mixed[2])

    return decision
