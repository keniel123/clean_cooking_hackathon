"""Standardization, temporal train/test splitting, and torch dataset helpers."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader, TensorDataset


@dataclass
class Standardizer:
    """Simple feature standardizer with saveable mean/std."""

    mean: np.ndarray
    std: np.ndarray

    @classmethod
    def fit(cls, matrix: np.ndarray) -> "Standardizer":
        mean = matrix.mean(axis=0)
        std = matrix.std(axis=0)
        std[std == 0] = 1.0
        return cls(mean=mean.astype(np.float32), std=std.astype(np.float32))

    def transform(self, matrix: np.ndarray) -> np.ndarray:
        return ((matrix - self.mean) / self.std).astype(np.float32)

    def to_dict(self) -> dict[str, list[float]]:
        return {"mean": self.mean.tolist(), "std": self.std.tolist()}

    @classmethod
    def from_dict(cls, payload: dict[str, list[float]]) -> "Standardizer":
        return cls(
            mean=np.asarray(payload["mean"], dtype=np.float32),
            std=np.asarray(payload["std"], dtype=np.float32),
        )


def temporal_mask(dates: pd.Series, cutoff_date: str) -> tuple[np.ndarray, np.ndarray]:
    """Boolean masks (train, test): rows on/before cutoff train, after cutoff test."""
    as_dates = pd.to_datetime(dates)
    cutoff = pd.to_datetime(cutoff_date)
    train = (as_dates <= cutoff).to_numpy()
    return train, ~train


def make_loader(*tensors: torch.Tensor, batch_size: int, shuffle: bool) -> DataLoader:
    return DataLoader(TensorDataset(*tensors), batch_size=batch_size, shuffle=shuffle)


def to_tensor(array: np.ndarray, dtype: torch.dtype = torch.float32) -> torch.Tensor:
    return torch.as_tensor(array, dtype=dtype)
