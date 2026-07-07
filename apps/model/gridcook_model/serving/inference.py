"""Load the trained recommender and turn its outputs into credit recommendations.

The credit arithmetic mirrors the API's rules baseline so ``nn-v1`` values are
directly comparable to ``rules-v1``; the difference is that the slot color and
expected kWh now come from the learned model instead of hourly averages.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import torch

from ..data import features
from ..data.dataset import Standardizer
from ..models import Recommender
from ..registry import latest_version, load_checkpoint

MODEL_NAME = "recommender"

REWARD_CREDITS_PER_KWH = 10.0
SLOT_CREDIT_MULTIPLIER = {"green": 1.0, "orange": 0.5, "red": 0.0}
SHIFTED_DAYTIME_BONUS_CREDITS = 8
DAYTIME_START_HOUR = 10
DAYTIME_END_HOUR = 15
HOURS_PER_DAY = 24


def has_trained_recommender() -> bool:
    return latest_version(MODEL_NAME) is not None


def _derive_credit(slot_color: str, expected_kwh: float, hour: int) -> tuple[int, str]:
    multiplier = SLOT_CREDIT_MULTIPLIER.get(slot_color, 0.0)
    energy_credits = expected_kwh * REWARD_CREDITS_PER_KWH * multiplier
    in_daytime = DAYTIME_START_HOUR <= hour <= DAYTIME_END_HOUR
    shift_bonus = SHIFTED_DAYTIME_BONUS_CREDITS if in_daytime and slot_color != "red" else 0
    suggested = int(round(energy_credits)) + shift_bonus
    basis = (
        f"model {slot_color} window x{multiplier:g} on {expected_kwh:.2f} kWh"
        + (f" + {shift_bonus} daytime-shift bonus" if shift_bonus else "")
    )
    return suggested, basis


class RecommenderService:
    """Wraps a trained recommender checkpoint for per-(account, hour) prediction."""

    def __init__(self) -> None:
        module, metadata = load_checkpoint(MODEL_NAME, Recommender)
        self.model = module
        self.model_version = metadata["model_version"]
        self.standardizer = Standardizer.from_dict(metadata["standardizer"])

    def predict(self, account_id: str, hour: int) -> dict[str, Any] | None:
        row = features.account_grid_feature_row(account_id, hour)
        if row is None:
            return None
        feature_vector, _ = row
        standardized = self.standardizer.transform(feature_vector[np.newaxis, :])
        with torch.no_grad():
            slot_logits, kwh = self.model(torch.as_tensor(standardized, dtype=torch.float32))
        slot_index = int(torch.argmax(slot_logits, dim=1).item())
        slot_color = features.INDEX_TO_SLOT[slot_index]
        expected_kwh = round(float(kwh.item()), 3)
        suggested, basis = _derive_credit(slot_color, expected_kwh, hour)
        return {
            "slot_color": slot_color,
            "expected_kwh": expected_kwh,
            "suggested_credit_gain": suggested,
            "credit_gain_basis": basis,
            "model_version": self.model_version,
        }


def build_hourly_table() -> dict[str, Any]:
    """Grid-level per-hour predictions, averaged over all accounts.

    Produces the compact artifact the API consumes so it needs no torch at
    runtime: {"model_version", "generated_hours": {hour: {...}}}.
    """
    service = RecommenderService()
    account_table, _ = features.build_account_feature_table()
    account_ids = list(account_table.index)

    hours: dict[str, Any] = {}
    for hour in range(HOURS_PER_DAY):
        slot_votes = np.zeros(len(features.SLOT_COLORS))
        kwh_values: list[float] = []
        for account_id in account_ids:
            prediction = service.predict(account_id, hour)
            if prediction is None:
                continue
            slot_votes[features.SLOT_TO_INDEX[prediction["slot_color"]]] += 1
            kwh_values.append(prediction["expected_kwh"])
        if not kwh_values:
            continue
        slot_color = features.INDEX_TO_SLOT[int(slot_votes.argmax())]
        expected_kwh = round(float(np.mean(kwh_values)), 3)
        suggested, basis = _derive_credit(slot_color, expected_kwh, hour)
        hours[str(hour)] = {
            "slot_color": slot_color,
            "expected_kwh": expected_kwh,
            "suggested_credit_gain": suggested,
            "credit_gain_basis": basis,
        }
    return {"model_version": service.model_version, "generated_hours": hours}
