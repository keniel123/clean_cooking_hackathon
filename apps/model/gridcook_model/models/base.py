"""Shared base class for GridCook models."""

from __future__ import annotations

from typing import Any

import torch
from torch import nn


class GridCookModule(nn.Module):
    """Base module that records the config needed to rebuild the model.

    ``config`` holds the constructor arguments so a checkpoint can be reloaded
    without hardcoding shapes elsewhere.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__()
        self.config = dict(config)

    def state_payload(self) -> dict[str, Any]:
        return {"config": self.config, "state_dict": self.state_dict()}


def mlp(input_dim: int, hidden_dim: int, output_dim: int, depth: int = 2) -> nn.Sequential:
    """Small multilayer perceptron with ReLU activations."""
    layers: list[nn.Module] = [nn.Linear(input_dim, hidden_dim), nn.ReLU()]
    for _ in range(max(0, depth - 1)):
        layers += [nn.Linear(hidden_dim, hidden_dim), nn.ReLU()]
    layers.append(nn.Linear(hidden_dim, output_dim))
    return nn.Sequential(*layers)
