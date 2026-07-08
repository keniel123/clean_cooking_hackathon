"""Generic supervised training loop shared by all models."""

from __future__ import annotations

from typing import Callable

import torch
from torch import nn
from torch.utils.data import DataLoader

LossFn = Callable[[nn.Module, tuple[torch.Tensor, ...]], torch.Tensor]


def train(model: nn.Module, loader: DataLoader, loss_fn: LossFn, *,
          epochs: int = 30, lr: float = 1e-3, weight_decay: float = 1e-4,
          device: str = "cpu") -> list[float]:
    """Train ``model`` in place. ``loss_fn`` maps (model, batch) -> scalar loss.

    Returns the mean loss per epoch.
    """
    model.to(device)
    model.train()
    optimizer = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=weight_decay)

    epoch_losses: list[float] = []
    for _ in range(epochs):
        batch_losses: list[float] = []
        for batch in loader:
            batch = tuple(tensor.to(device) for tensor in batch)
            optimizer.zero_grad()
            loss = loss_fn(model, batch)
            loss.backward()
            optimizer.step()
            batch_losses.append(loss.item())
        epoch_losses.append(sum(batch_losses) / max(1, len(batch_losses)))
    return epoch_losses
