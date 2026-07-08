"""Cooking-demand forecaster (D): per-hour features -> [sessions, kWh]."""

from __future__ import annotations

import torch
from torch import nn

from .base import GridCookModule, mlp


class DemandForecaster(GridCookModule):
    """Regress expected cooking sessions and kWh for an hour.

    Uses a softplus output so predictions stay non-negative.
    """

    def __init__(self, num_features: int, num_targets: int = 2, hidden_dim: int = 32) -> None:
        super().__init__({
            "num_features": num_features,
            "num_targets": num_targets,
            "hidden_dim": hidden_dim,
        })
        self.net = mlp(num_features, hidden_dim, num_targets)
        self.activation = nn.Softplus()

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        return self.activation(self.net(features))
