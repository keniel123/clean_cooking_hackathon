"""Recommender/credit model (C): multi-task slot suitability + expected kWh.

Shared trunk with two heads. The credit gain itself is derived from the two
learned outputs (predicted slot color + expected kWh) by the serving layer, so
the value is model-driven while the final arithmetic stays explainable.
"""

from __future__ import annotations

import torch
from torch import nn

from .base import GridCookModule


class Recommender(GridCookModule):
    def __init__(self, num_features: int, num_classes: int = 3, hidden_dim: int = 48) -> None:
        super().__init__({
            "num_features": num_features,
            "num_classes": num_classes,
            "hidden_dim": hidden_dim,
        })
        self.trunk = nn.Sequential(
            nn.Linear(num_features, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
        )
        self.slot_head = nn.Linear(hidden_dim, num_classes)
        self.kwh_head = nn.Sequential(nn.Linear(hidden_dim, 1), nn.Softplus())

    def forward(self, features: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        hidden = self.trunk(features)
        return self.slot_head(hidden), self.kwh_head(hidden)
