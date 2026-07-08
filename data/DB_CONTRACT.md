# Oloika DB contract

## Files

| File | Purpose |
|---|---|
| `data/load_oloika_dataset_sqlite.py` | Build/seed `oloika.sqlite` from `data/synthetic/*.csv` |
| `data/oloika_write.py` | The write path. The API calls this; it owns integrity |
| `data/test_oloika_write.py` | Test suite for the write path |
| `data/migrate.py` | Versioned migrations (`PRAGMA user_version`) + online backup |
| `data/migrations/*.sql` | Numbered migrations |

## Build

```bash
python data/load_oloika_dataset_sqlite.py            # -> data/oloika.sqlite
python data/load_oloika_dataset_sqlite.py --out /data/oloika.sqlite
python data/load_oloika_dataset_sqlite.py --check    # verify, no write
python data/migrate.py --db /data/oloika.sqlite      # apply pending migrations
```

Exits non-zero on any integrity failure, so it is safe to gate CI on.

The synthetic CSVs are currently gitignored. Restore `data/synthetic/` before building, or the script exits with a clear error.

## Indexes

All API filter columns are indexed and confirmed used by the query planner (no table scans): `account_id`, `date`, `slot_color`, `hour_eat`, `cooker_id`, plus `session_id`, `event_type`, `entity_id`, `community_id`, `plug`. 28 indexes total.

## The write path

```python
from data.oloika_write import (
    connect, complete_session, top_up, refresh_leaderboard,
    InsufficientCredits, SessionAlreadyBilled, UnknownAccount,
)

con = connect("/data/oloika.sqlite")   # sets WAL + busy_timeout + FK on

result = complete_session(
    con,
    session_id="SESS-123",
    account_id="HH-0020",
    kwh=0.42,
    slot_color="green",         # green | orange | red
    cooker_id="CK-007",
    shifted_daytime=1,
    start_at="2025-06-20T12:00:00",
)
# -> {"credits_charged": 11, "credits_rewarded": 13, "net_credits": 2,
#     "balance_after": 137, ...}
```

`complete_session` is **one atomic transaction**: it ensures the `cooking_sessions` row exists, inserts the `cook_charge`, inserts the reward if the slot earns one, and updates `credit_balances`. Any failure rolls the whole thing back.

**Exceptions the API must handle:**

| Exception | Meaning | Suggested HTTP |
|---|---|---|
| `InsufficientCredits` | Charge would take balance below zero. Nothing written | 402 |
| `SessionAlreadyBilled` | This `session_id` already has a `cook_charge`. Safe to retry | 409 (or 200, idempotent) |
| `UnknownAccount` | No such `account_id` | 404 |
| `WriteError` | Bad `slot_color`, negative kwh, etc. | 400 |

`top_up(con, account_id, cash_kes)` is also atomic and always increases the balance.

### Leaderboard

`refresh_leaderboard(con)` rebuilds the table from `cooking_sessions` + `billing_ledger`. It is **deliberately not inside** `complete_session` — refreshing 84 rows on every cook would lock the table for no benefit. Call it on a timer (every N seconds), after a batch, or lazily before serving `GET /leaderboard`.

Verified: it reproduces the seeded leaderboard column-for-column across all 84 rows.

Score formula (reverse-engineered from the seed, exact, zero residual):

```
score = credits_earned + 5*green + 1*orange - 5*red + 8*shifted_daytime + sessions
```

### Rates (new sessions only)

Constants at the top of `oloika_write.py`:

```python
CREDITS_PER_KWH_CHARGE = 25
GREEN_REWARD_PER_KWH   = 30
ORANGE_REWARD_PER_KWH  = 8      # exact in seed
RED_REWARD_PER_KWH     = 0
CREDITS_PER_KES        = 2      # exact in seed
```

The seeded June-2025 ledger was generated with jitter and is **not** an exact function of the stored 3dp-rounded `kwh`, so history cannot be recomputed from `kwh`. These rates therefore govern new sessions only; existing rows are never rewritten. Orange and top-up rates are exact; the charge and green rates are the best fit to the seed's central tendency and are a product decision — change them in one place.

## Defaults I chose (say if you want them different)

1. **Leaderboard stays a physical table** (the API reads it directly), refreshed outside the write transaction.
2. **Credits cannot go negative on spend.** A cook that would overdraw is *rejected* (`InsufficientCredits`) rather than allowed-and-flagged. Top-ups and rewards are unconstrained. Enforced both in code and by `CHECK (ending_balance_credits >= 0)` / `CHECK (balance_after >= 0)`.

Both are one-line changes if the product call goes the other way. Rejecting an overdraw means a user with no credits cannot cook — if the demo needs cooking to always succeed, flip this to allow-and-flag.

## Concurrency

`connect()` sets `journal_mode=WAL`, `busy_timeout=10000`, `foreign_keys=ON`. `complete_session` uses `BEGIN IMMEDIATE` so the read-then-write of the balance cannot interleave with another writer.

Tested: 4 concurrent writer threads × 10 sessions each → all 40 billed exactly once, no corruption, no deadlock, invariants hold.

This is sufficient for a mounted SQLite file with a multi-worker API. If you later see `database is locked` under real load, that's the signal to move to Postgres — not before.

## Backups

```bash
python data/migrate.py --db /data/oloika.sqlite --backup /data/backups/
```

Uses SQLite's online backup API, which is safe on a live database. `cp` is **not** — it can capture a torn WAL. Wire it to cron/systemd-timer at whatever cadence you like.

## Open questions for you

1. **Is `/data/` a persistent volume?** If the container filesystem resets on redeploy, mounting there does not make the DB persistent — it just moves the problem. Worth confirming with whoever owns the server config before we call this done.
2. **Overdraw behaviour** — reject (current) or allow-and-flag? Product call.
3. **Charge/reward rates** — the numbers above are defaults, not derived truth. Confirm or replace.
