from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data" / "synthetic"


def _csv_rows(filename: str) -> list[dict[str, str]]:
    with (DATA_DIR / filename).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


@lru_cache(maxsize=16)
def accounts() -> list[dict[str, str]]:
    return _csv_rows("oloika_minigrid_accounts.csv")


@lru_cache(maxsize=16)
def credit_balances() -> list[dict[str, str]]:
    return _csv_rows("oloika_credit_balances_june_2025.csv")


@lru_cache(maxsize=16)
def leaderboard() -> list[dict[str, str]]:
    return _csv_rows("oloika_leaderboard_june_2025.csv")


@lru_cache(maxsize=16)
def daily_behavior() -> list[dict[str, str]]:
    return _csv_rows("oloika_account_daily_behavior_june_2025.csv")


@lru_cache(maxsize=16)
def cookers() -> list[dict[str, str]]:
    return _csv_rows("oloika_cooker_assets.csv")


def get_account(account_id: str) -> dict[str, str] | None:
    return next((row for row in accounts() if row["account_id"] == account_id), None)


def account_profile(account_id: str) -> dict[str, Any] | None:
    account = get_account(account_id)
    if account is None:
        return None
    balance = next((row for row in credit_balances() if row["account_id"] == account_id), {})
    board = next((row for row in leaderboard() if row["account_id"] == account_id), {})
    behavior_rows = [row for row in daily_behavior() if row["account_id"] == account_id]
    latest_behavior = sorted(behavior_rows, key=lambda row: row["date"])[-1] if behavior_rows else {}
    account_cookers = [row for row in cookers() if row["account_id"] == account_id]
    return {
        "account": account,
        "credit_balance": balance,
        "leaderboard": board,
        "latest_behavior": latest_behavior,
        "cookers": account_cookers,
    }


def known_cooker(account_id: str, cooker_id: str | None) -> bool:
    if cooker_id is None:
        return True
    return any(row["account_id"] == account_id and row["cooker_id"] == cooker_id for row in cookers())
