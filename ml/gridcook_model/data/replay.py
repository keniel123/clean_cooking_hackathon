"""Reservoir replay buffer for continual learning.

Holds a bounded sample of historical training examples so that continual
fine-tuning on new data can mix in past examples and avoid catastrophic
forgetting.
"""

from __future__ import annotations

import numpy as np


class ReplayBuffer:
    """Fixed-capacity reservoir buffer over feature/label arrays."""

    def __init__(self, capacity: int, seed: int = 42) -> None:
        self.capacity = capacity
        self._rng = np.random.default_rng(seed)
        self._arrays: list[np.ndarray] | None = None
        self._seen = 0

    def __len__(self) -> int:
        return 0 if self._arrays is None else len(self._arrays[0])

    def add(self, *arrays: np.ndarray) -> None:
        """Add a batch of aligned arrays (e.g. features, labels) via reservoir sampling."""
        batch_size = len(arrays[0])
        if self._arrays is None:
            self._arrays = [array[:0].copy() for array in arrays]

        for index in range(batch_size):
            sample = [array[index] for array in arrays]
            if len(self) < self.capacity:
                self._append(sample)
            else:
                slot = self._rng.integers(0, self._seen + 1)
                if slot < self.capacity:
                    self._replace(slot, sample)
            self._seen += 1

    def _append(self, sample: list[np.ndarray]) -> None:
        for position, value in enumerate(sample):
            self._arrays[position] = np.concatenate(
                [self._arrays[position], value[np.newaxis, ...]], axis=0
            )

    def _replace(self, slot: int, sample: list[np.ndarray]) -> None:
        for position, value in enumerate(sample):
            self._arrays[position][slot] = value

    def sample(self, count: int) -> list[np.ndarray]:
        """Return a random sample of up to ``count`` aligned rows."""
        if self._arrays is None or len(self) == 0:
            return []
        take = min(count, len(self))
        indices = self._rng.choice(len(self), size=take, replace=False)
        return [array[indices] for array in self._arrays]
