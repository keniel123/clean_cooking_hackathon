"""Grid/solar forecaster (F): GRU over hourly telemetry -> next-horizon targets."""

from __future__ import annotations

import torch
from torch import nn

from .base import GridCookModule


class GridForecaster(GridCookModule):
    """Encode a lookback window with a GRU and predict the next ``horizon`` steps.

    Output shape: (batch, horizon, num_targets), for pv / battery_soc / load.
    """

    def __init__(self, num_features: int, num_targets: int, horizon: int,
                 hidden_dim: int = 32) -> None:
        super().__init__({
            "num_features": num_features,
            "num_targets": num_targets,
            "horizon": horizon,
            "hidden_dim": hidden_dim,
        })
        self.horizon = horizon
        self.num_targets = num_targets
        self.encoder = nn.GRU(num_features, hidden_dim, batch_first=True)
        self.head = nn.Linear(hidden_dim, horizon * num_targets)

    def forward(self, sequence: torch.Tensor) -> torch.Tensor:
        _, hidden = self.encoder(sequence)
        flat = self.head(hidden.squeeze(0))
        return flat.view(-1, self.horizon, self.num_targets)
