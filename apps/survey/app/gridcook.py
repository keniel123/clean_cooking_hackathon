"""Enrol the mini-grid accounts served by a GridCook API (apps/api) as panel
respondents, so the survey studies the same customers the rest of the stack
(dashboard, mobile app) serves. `account_id` is the join key throughout.

The GridCook dataset is privacy-preserving (synthetic IDs, no contact
details), so each account gets a stable placeholder phone number derived from
its account ID — the *same* FNV-1a derivation the monitoring dashboard uses
(apps/dashboard, src/data/http/HttpDataProvider.ts), so account ID and phone
line up across apps end to end.
"""

from __future__ import annotations

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .models import Respondent

PAGE_SIZE = 500


def fnv1a32(text: str) -> int:
    """32-bit FNV-1a, bit-for-bit equal to the dashboard's `hashString`."""
    h = 0x811C9DC5
    for ch in text:
        h ^= ord(ch)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def synthetic_phone(account_id: str) -> str:
    """Deterministic Kenyan mobile placeholder, e.g. HH-0007 -> +254732026437."""
    digits = f"{fnv1a32(account_id) % 10**8:08d}"
    return f"+2547{digits}"


def display_name(account: dict) -> str:
    kind = "Business" if account.get("account_type") == "commercial" else "Household"
    return f"{kind} {account['account_id']}"


def fetch_accounts(base_url: str) -> list[dict]:
    """Every account from GET /api/v1/accounts, following the list envelope."""
    base = base_url.rstrip("/")
    results: list[dict] = []
    with httpx.Client(timeout=30) as client:
        while True:
            resp = client.get(
                f"{base}/api/v1/accounts",
                params={"limit": PAGE_SIZE, "offset": len(results)},
            )
            resp.raise_for_status()
            page = resp.json()
            results.extend(page["results"])
            if len(results) >= page["count"] or not page["results"]:
                return results


def import_accounts(db: Session, accounts: list[dict], site: str | None = None) -> tuple[int, int]:
    """Register accounts as respondents; returns (added, already_registered)."""
    added = skipped = 0
    for account in accounts:
        account_id = account["account_id"]
        phone = synthetic_phone(account_id)
        exists = db.scalar(
            select(Respondent).where(
                or_(Respondent.account_id == account_id, Respondent.phone == phone)
            )
        )
        if exists:
            skipped += 1
            continue
        db.add(
            Respondent(
                phone=phone,
                account_id=account_id,
                name=display_name(account),
                site=site or account.get("community_id"),
                meta={
                    "account_type": account.get("account_type"),
                    "entity_id": account.get("entity_id"),
                    "meter_status": account.get("meter_status"),
                    "phone_is_synthetic": True,
                },
            )
        )
        added += 1
    db.commit()
    return added, skipped
