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

# Smart, model-derived reward. Only green windows earn credit; among green hours
# the reward is a continuous value the model drives, so a "strongly green, high
# solar, underused, big behavior-shift" session is worth far more than a barely
# green one. Whole credits are realized by accumulation (see db.award_session_credit).
#
#   reward = BASE x P(green) x grid_benefit x (1 + SHIFT_WEIGHT x shift_value)
#
# BASE sets the ceiling for a strong green session; the factors (all in [0, 1]
# except the shift multiplier) keep typical rewards near ~0.1 and cap at 1.0.
BASE_REWARD = 0.2
SHIFT_WEIGHT = 0.5
MAX_SESSION_CREDIT = 1.0
HOURS_PER_DAY = 24


def has_trained_recommender() -> bool:
    return latest_version(MODEL_NAME) is not None


def smart_reward(slot_color: str, green_probability: float, hour: int,
                 green_window_share: float) -> tuple[float, str]:
    """Model-derived personalized reward for a session; 0 for non-green windows.

    - ``green_probability``: model confidence this is genuinely a good hour.
    - ``grid_benefit``: solar surplus / low stress at the hour (learned from data).
    - ``shift_value``: personalization - users who habitually cook in bad windows
      (low ``green_window_share``) earn more for shifting to green.
    """
    if slot_color != "green":
        return 0.0, f"{slot_color} window earns no credit"

    grid_benefit = features.grid_benefit_by_hour().get(int(hour), 0.5)
    shift_value = max(0.0, 1.0 - float(green_window_share))
    shift_multiplier = 1.0 + SHIFT_WEIGHT * shift_value
    reward = BASE_REWARD * float(green_probability) * grid_benefit * shift_multiplier
    reward = round(min(reward, MAX_SESSION_CREDIT), 3)
    basis = (
        f"smart: P(green)={green_probability:.2f} x grid_benefit={grid_benefit:.2f} "
        f"x shift={shift_multiplier:.2f}"
    )
    return reward, basis


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
        feature_vector, columns = row
        standardized = self.standardizer.transform(feature_vector[np.newaxis, :])
        with torch.no_grad():
            slot_logits, kwh = self.model(torch.as_tensor(standardized, dtype=torch.float32))
        probabilities = torch.softmax(slot_logits, dim=1).squeeze(0)
        slot_index = int(torch.argmax(probabilities).item())
        slot_color = features.INDEX_TO_SLOT[slot_index]
        green_probability = float(probabilities[features.SLOT_TO_INDEX["green"]].item())
        expected_kwh = round(float(kwh.item()), 3)

        green_window_share = float(feature_vector[columns.index("green_window_share")])
        suggested, basis = smart_reward(slot_color, green_probability, hour, green_window_share)
        return {
            "slot_color": slot_color,
            "green_probability": round(green_probability, 3),
            "expected_kwh": expected_kwh,
            "suggested_credit_gain": suggested,
            "credit_gain_basis": basis,
            "model_version": self.model_version,
        }


def build_hourly_table() -> dict[str, Any]:
    """Grid-level and account-level per-hour predictions.

    Produces the compact artifact the API consumes so it needs no torch at
    runtime. ``generated_hours`` is the backward-compatible community average;
    ``account_hours`` preserves personalized per-account recommendations.
    """
    service = RecommenderService()
    account_table, _ = features.build_account_feature_table()
    account_ids = list(account_table.index)

    hours: dict[str, Any] = {}
    account_hours: dict[str, dict[str, Any]] = {account_id: {} for account_id in account_ids}
    for hour in range(HOURS_PER_DAY):
        slot_votes = np.zeros(len(features.SLOT_COLORS))
        kwh_values: list[float] = []
        reward_values: list[float] = []
        for account_id in account_ids:
            prediction = service.predict(account_id, hour)
            if prediction is None:
                continue
            account_hours[account_id][str(hour)] = {
                "slot_color": prediction["slot_color"],
                "expected_kwh": prediction["expected_kwh"],
                "suggested_credit_gain": prediction["suggested_credit_gain"],
                "credit_gain_basis": prediction["credit_gain_basis"],
            }
            slot_votes[features.SLOT_TO_INDEX[prediction["slot_color"]]] += 1
            kwh_values.append(prediction["expected_kwh"])
            reward_values.append(prediction["suggested_credit_gain"])
        if not kwh_values:
            continue
        slot_color = features.INDEX_TO_SLOT[int(slot_votes.argmax())]
        expected_kwh = round(float(np.mean(kwh_values)), 3)
        # Community credit = average smart reward across accounts for this hour.
        suggested = round(float(np.mean(reward_values)), 3)
        hours[str(hour)] = {
            "slot_color": slot_color,
            "expected_kwh": expected_kwh,
            "suggested_credit_gain": suggested,
            "credit_gain_basis": f"community avg smart reward ({slot_color})",
        }
    return {
        "model_version": service.model_version,
        "generated_hours": hours,
        "account_hours": account_hours,
    }
