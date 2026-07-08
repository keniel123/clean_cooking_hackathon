"""Grid-risk classifier (R): per-hour grid features -> slot color logits."""

from __future__ import annotations

import torch

from .base import GridCookModule, mlp


class RiskClassifier(GridCookModule):
    """Small MLP producing 3-class logits (green / orange / red)."""

    def __init__(self, num_features: int, num_classes: int = 3, hidden_dim: int = 32) -> None:
        super().__init__({
            "num_features": num_features,
            "num_classes": num_classes,
            "hidden_dim": hidden_dim,
        })
        self.net = mlp(num_features, hidden_dim, num_classes)

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        return self.net(features)
