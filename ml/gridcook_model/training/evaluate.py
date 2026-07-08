"""Evaluation metrics and non-learned baselines.

Every learned model is compared against a transparent baseline so a model is
only ever promoted when it actually helps.
"""

from __future__ import annotations

import numpy as np


def mae(predictions: np.ndarray, targets: np.ndarray) -> float:
    return float(np.mean(np.abs(predictions - targets)))


def macro_f1(predicted: np.ndarray, actual: np.ndarray, num_classes: int = 3) -> float:
    scores: list[float] = []
    for label in range(num_classes):
        true_positive = int(np.sum((predicted == label) & (actual == label)))
        false_positive = int(np.sum((predicted == label) & (actual != label)))
        false_negative = int(np.sum((predicted != label) & (actual == label)))
        denominator = 2 * true_positive + false_positive + false_negative
        scores.append(0.0 if denominator == 0 else 2 * true_positive / denominator)
    return float(np.mean(scores))


def confusion_matrix(predicted: np.ndarray, actual: np.ndarray, num_classes: int = 3) -> np.ndarray:
    matrix = np.zeros((num_classes, num_classes), dtype=int)
    for actual_label, predicted_label in zip(actual, predicted):
        matrix[int(actual_label), int(predicted_label)] += 1
    return matrix


def hour_of_day_baseline(train_hours: np.ndarray, train_targets: np.ndarray,
                         test_hours: np.ndarray) -> np.ndarray:
    """Predict each test hour with the mean training target for that hour."""
    global_mean = train_targets.mean(axis=0)
    predictions = np.tile(global_mean, (len(test_hours), 1))
    for hour in np.unique(train_hours):
        hour_mean = train_targets[train_hours == hour].mean(axis=0)
        predictions[test_hours == hour] = hour_mean
    return predictions


def majority_class_baseline(train_labels: np.ndarray, count: int) -> np.ndarray:
    majority = np.bincount(train_labels).argmax()
    return np.full(count, majority, dtype=train_labels.dtype)
