"""Replay-based continual learning: mix new data with history, fine-tune, promote.

The orchestration (evaluate candidate vs current, decide) lives in the caller so
these helpers stay small and reusable across models.
"""

from __future__ import annotations

import copy

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from ..data.replay import ReplayBuffer
from .trainer import LossFn, train


def build_finetune_arrays(new_arrays: list[np.ndarray], replay_buffer: ReplayBuffer,
                          replay_count: int) -> list[np.ndarray]:
    """Concatenate the new batch with a replay sample of historical rows."""
    replay = replay_buffer.sample(replay_count)
    if not replay:
        return list(new_arrays)
    return [np.concatenate([new, old], axis=0) for new, old in zip(new_arrays, replay)]


def replay_finetune(model: nn.Module, tensors: tuple[torch.Tensor, ...], loss_fn: LossFn, *,
                    epochs: int = 10, lr: float = 5e-4, batch_size: int = 64,
                    device: str = "cpu") -> tuple[nn.Module, list[float]]:
    """Warm-start fine-tune a copy of ``model`` on the given tensors."""
    candidate = copy.deepcopy(model)
    loader = DataLoader(TensorDataset(*tensors), batch_size=batch_size, shuffle=True)
    history = train(candidate, loader, loss_fn, epochs=epochs, lr=lr, device=device)
    return candidate, history


def promote_if_better(candidate_metric: float, current_metric: float,
                      baseline_metric: float, higher_is_better: bool) -> bool:
    """A candidate is promoted only if it matches/beats current and beats baseline."""
    def at_least_as_good(value: float, reference: float) -> bool:
        return value >= reference if higher_is_better else value <= reference

    def strictly_better(value: float, reference: float) -> bool:
        return value > reference if higher_is_better else value < reference

    return at_least_as_good(candidate_metric, current_metric) and \
        strictly_better(candidate_metric, baseline_metric)
