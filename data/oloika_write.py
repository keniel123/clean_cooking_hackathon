"""
oloika_write.py — the write path for the GridCook rewards loop.

The API calls these functions; they own correctness and integrity.
Everything that must not half-happen happens inside one transaction.

Design notes (agreed contract)
------------------------------
* complete_session() is atomic: insert cook_charge, insert reward (if any),
  update credit_balances. Either all of it lands or none of it does.
* The leaderboard is a DERIVED artifact. It is NOT refreshed inside the
  per-session transaction — that would make every cook lock the whole table.
  Call refresh_leaderboard() on a timer, or after a batch, or on read.
* Credits cannot go negative. A cook_charge that would overdraw is rejected
  with InsufficientCredits and the transaction rolls back. Top-ups and
  rewards are unconstrained (they only ever increase the balance).
* Idempotent: completing the same session_id twice raises SessionAlreadyBilled
  rather than double-charging. The API can safely retry.

Rates
-----
The seeded June-2025 ledger was generated with jitter and is NOT an exact
function of the stored (3dp-rounded) kwh, so it cannot be reproduced from
kwh alone. These constants therefore govern NEW sessions only; historical
rows are never recomputed. Change them here, in one place.
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

# ---- tariff / reward constants (new sessions only) -----------------------
CREDITS_PER_KWH_CHARGE = 25      # cook_charge = round(kwh * 25)
GREEN_REWARD_PER_KWH = 30        # green_reward = round(kwh * 30)
ORANGE_REWARD_PER_KWH = 8        # orange_reward = round(kwh * 8)   (exact in seed)
RED_REWARD_PER_KWH = 0           # red slots earn nothing
CREDITS_PER_KES = 2              # top_up: 1 KES -> 2 credits       (exact in seed)
MIN_CHARGE_CREDITS = 1           # never charge 0 for a real cook

REWARD_EVENT = {"green": "green_reward", "orange": "orange_reward", "red": None}

# leaderboard score weights — verified to reproduce the seed exactly
SCORE_SQL = ("credits_earned + 5*green_sessions + 1*orange_sessions "
             "- 5*red_sessions + 8*shifted_daytime_sessions + sessions")


class WriteError(Exception):
    """Base class for write-path failures."""


class InsufficientCredits(WriteError):
    def __init__(self, account_id, balance, needed):
        self.account_id, self.balance, self.needed = account_id, balance, needed
        super().__init__(
            f"{account_id}: balance {balance} < charge {needed}"
        )


class SessionAlreadyBilled(WriteError):
    pass


class UnknownAccount(WriteError):
    pass


# --------------------------------------------------------------------------
def connect(path: str) -> sqlite3.Connection:
    """Open the canonical DB with the pragmas the API needs.

    WAL lets many readers coexist with one writer; busy_timeout stops
    'database is locked' from surfacing as a 500 under concurrent requests.
    """
    con = sqlite3.connect(path, isolation_level=None, timeout=10.0)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA synchronous = NORMAL")
    con.execute("PRAGMA busy_timeout = 10000")
    return con


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ledger_id() -> str:
    return f"LDG-{uuid.uuid4().hex[:12]}"


def _month(date_str: str) -> str:
    return date_str[:7]  # 'YYYY-MM'


def _latest_balance_month(con: sqlite3.Connection, account_id: str, fallback: str) -> str:
    """The account's most recent balance-sheet month (where its wallet lives),
    or `fallback` if it has none yet. Keeps writes on the seeded demo month
    rather than spawning a fresh zero balance in a later calendar month."""
    row = con.execute(
        "SELECT month FROM credit_balances WHERE account_id = ? "
        "ORDER BY month DESC LIMIT 1", (account_id,)
    ).fetchone()
    return row["month"] if row else fallback


def charge_for(kwh: float) -> int:
    return max(MIN_CHARGE_CREDITS, round(kwh * CREDITS_PER_KWH_CHARGE))


def reward_for(kwh: float, slot_color: str) -> int:
    rate = {"green": GREEN_REWARD_PER_KWH,
            "orange": ORANGE_REWARD_PER_KWH,
            "red": RED_REWARD_PER_KWH}.get(slot_color, 0)
    return round(kwh * rate)


# --------------------------------------------------------------------------
def complete_session(
    con: sqlite3.Connection,
    session_id: str,
    account_id: str,
    kwh: float,
    slot_color: str,
    *,
    cooker_id: str | None = None,
    shifted_daytime: int = 0,
    start_at: str | None = None,
    end_at: str | None = None,
) -> dict:
    """Bill a completed cooking session. Atomic.

    Inserts cook_charge (+ reward if the slot earns one) into billing_ledger
    and updates credit_balances. Rolls back entirely on any failure.

    Raises InsufficientCredits if the charge would take the balance below zero.
    Raises SessionAlreadyBilled if this session_id already has a cook_charge.

    Returns a summary dict for the API to hand back to the client.
    """
    if slot_color not in REWARD_EVENT:
        raise WriteError(f"unknown slot_color {slot_color!r}")
    if kwh < 0:
        raise WriteError("kwh must be >= 0")

    charge = charge_for(kwh)
    reward = reward_for(kwh, slot_color)
    reward_event = REWARD_EVENT[slot_color]
    now = _now()

    # IMMEDIATE takes the write lock up front, so the read-then-write of the
    # balance can't interleave with another writer's.
    con.execute("BEGIN IMMEDIATE")
    try:
        acct = con.execute(
            "SELECT account_id, account_type, entity_id FROM minigrid_accounts "
            "WHERE account_id = ?", (account_id,)
        ).fetchone()
        if acct is None:
            raise UnknownAccount(account_id)

        dup = con.execute(
            "SELECT 1 FROM billing_ledger WHERE session_id = ? AND event_type = 'cook_charge'",
            (session_id,),
        ).fetchone()
        if dup:
            raise SessionAlreadyBilled(session_id)

        # billing_ledger.session_id has an FK to cooking_sessions, so the session
        # row must exist before we can bill it. If POST /sessions/start already
        # created it, update the outcome; otherwise create it here. Either way
        # it happens inside this transaction.
        exists = con.execute(
            "SELECT 1 FROM cooking_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if exists:
            con.execute(
                """UPDATE cooking_sessions
                      SET kwh = ?, slot_color = ?, shifted_daytime = ?,
                          end_at = COALESCE(?, end_at)
                    WHERE session_id = ?""",
                (kwh, slot_color, shifted_daytime, end_at, session_id),
            )
        else:
            con.execute(
                """INSERT INTO cooking_sessions
                   (session_id, account_id, entity_id, account_type, cooker_id,
                    start_at, end_at, date, kwh, slot_color, shifted_daytime, source)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,'app')""",
                (session_id, account_id, acct["entity_id"], acct["account_type"],
                 cooker_id, start_at or now, end_at or now, (start_at or now)[:10],
                 kwh, slot_color, shifted_daytime),
            )

        # Bill against the account's current balance sheet (seeded demo month),
        # not the session's calendar month, so the wallet stays coherent.
        month = _latest_balance_month(con, account_id, _month((start_at or now)[:10]))
        bal_row = con.execute(
            "SELECT ending_balance_credits FROM credit_balances "
            "WHERE account_id = ? AND month = ?", (account_id, month)
        ).fetchone()
        balance = bal_row["ending_balance_credits"] if bal_row else 0

        # --- the guard the brief asked for
        if balance - charge < 0:
            raise InsufficientCredits(account_id, balance, charge)

        balance -= charge
        con.execute(
            """INSERT INTO billing_ledger
               (ledger_id, account_id, event_type, session_id, credits_delta,
                cash_kes, balance_after, reason, created_at)
               VALUES (?,?,'cook_charge',?,?,0,?,?,?)""",
            (_ledger_id(), account_id, session_id, -charge, balance,
             f"cook {kwh:.3f} kWh ({slot_color})", now),
        )

        if reward_event and reward > 0:
            balance += reward
            con.execute(
                """INSERT INTO billing_ledger
                   (ledger_id, account_id, event_type, session_id, credits_delta,
                    cash_kes, balance_after, reason, created_at)
                   VALUES (?,?,?,?,?,0,?,?,?)""",
                (_ledger_id(), account_id, reward_event, session_id, reward,
                 balance, f"{slot_color} window reward", now),
            )
        else:
            reward = 0

        if bal_row:
            con.execute(
                """UPDATE credit_balances SET
                     ending_balance_credits = ?,
                     total_reward_credits   = total_reward_credits + ?,
                     total_spent_credits    = total_spent_credits + ?
                   WHERE account_id = ? AND month = ?""",
                (balance, reward, charge, account_id, month),
            )
        else:
            con.execute(
                """INSERT INTO credit_balances
                   (account_id, account_type, entity_id, month,
                    ending_balance_credits, total_top_up_credits,
                    total_reward_credits, total_spent_credits, cash_paid_kes)
                   VALUES (?,?,?,?,?,0,?,?,0)""",
                (account_id, acct["account_type"], acct["entity_id"], month,
                 balance, reward, charge),
            )

        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise

    return {
        "session_id": session_id,
        "account_id": account_id,
        "kwh": kwh,
        "slot_color": slot_color,
        "credits_charged": charge,
        "credits_rewarded": reward,
        "net_credits": reward - charge,
        "balance_after": balance,
    }


# --------------------------------------------------------------------------
def award_session(con: sqlite3.Connection, session_id: str, account_id: str,
                  kwh: float, slot_color: str, *,
                  cooker_id: str | None = None, shifted_daytime: int = 0,
                  start_at: str | None = None, reason: str | None = None) -> dict:
    """Record a session and AWARD credits for it — award-only, no energy charge
    (the incentive model). Atomic, on the same credit_balances ledger as
    complete_session/top_up so there is one canonical wallet.

    The reward is the ledger-native amount from the rate table
    (``reward_for(kwh, slot_color)``): the model decides *when* to cook and the
    slot colour, this ledger decides *how many* credits. The model's fractional
    ``suggested_credit_gain`` stays on the session as a nudge score; it is not
    the wallet amount (an integer ledger would truncate it to 0).

    Raises UnknownAccount / SessionAlreadyBilled (if already awarded) / WriteError.
    """
    if slot_color not in REWARD_EVENT:
        raise WriteError(f"unknown slot_color {slot_color!r}")
    if kwh < 0:
        raise WriteError("kwh must be >= 0")
    credits = reward_for(kwh, slot_color)
    now = _now()

    con.execute("BEGIN IMMEDIATE")
    try:
        acct = con.execute(
            "SELECT account_id, account_type, entity_id FROM minigrid_accounts "
            "WHERE account_id = ?", (account_id,)
        ).fetchone()
        if acct is None:
            raise UnknownAccount(account_id)

        dup = con.execute(
            "SELECT 1 FROM billing_ledger WHERE session_id = ? "
            "AND event_type IN ('green_reward','orange_reward','cook_charge')",
            (session_id,),
        ).fetchone()
        if dup:
            raise SessionAlreadyBilled(session_id)

        exists = con.execute(
            "SELECT 1 FROM cooking_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if exists:
            con.execute(
                "UPDATE cooking_sessions SET kwh = ?, slot_color = ?, shifted_daytime = ? "
                "WHERE session_id = ?", (kwh, slot_color, shifted_daytime, session_id),
            )
        else:
            con.execute(
                """INSERT INTO cooking_sessions
                   (session_id, account_id, entity_id, account_type, cooker_id,
                    start_at, end_at, date, kwh, slot_color, shifted_daytime, source)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,'app')""",
                (session_id, account_id, acct["entity_id"], acct["account_type"],
                 cooker_id, start_at or now, now, (start_at or now)[:10],
                 kwh, slot_color, shifted_daytime),
            )

        month = _latest_balance_month(con, account_id, _month((start_at or now)[:10]))
        bal_row = con.execute(
            "SELECT ending_balance_credits FROM credit_balances "
            "WHERE account_id = ? AND month = ?", (account_id, month)
        ).fetchone()
        old_balance = bal_row["ending_balance_credits"] if bal_row else 0

        # Award uses the slot's reward event type — the schema's CHECK allows only
        # green_reward / orange_reward / cook_charge / top_up. Red slots earn nothing.
        reward_event = REWARD_EVENT[slot_color]
        if reward_event and credits > 0:
            balance = old_balance + credits
            con.execute(
                """INSERT INTO billing_ledger
                   (ledger_id, account_id, event_type, session_id, credits_delta,
                    cash_kes, balance_after, reason, created_at)
                   VALUES (?,?,?,?,?,0,?,?,?)""",
                (_ledger_id(), account_id, reward_event, session_id, credits, balance,
                 reason or f"{slot_color} window reward", now),
            )
        else:
            credits, balance = 0, old_balance

        if bal_row:
            con.execute(
                "UPDATE credit_balances SET ending_balance_credits = ?, "
                "total_reward_credits = total_reward_credits + ? "
                "WHERE account_id = ? AND month = ?",
                (balance, credits, account_id, month),
            )
        else:
            con.execute(
                """INSERT INTO credit_balances
                   (account_id, account_type, entity_id, month, ending_balance_credits,
                    total_top_up_credits, total_reward_credits, total_spent_credits, cash_paid_kes)
                   VALUES (?,?,?,?,?,0,?,0,0)""",
                (account_id, acct["account_type"], acct["entity_id"], month, balance, credits),
            )
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise

    return {"session_id": session_id, "account_id": account_id, "kwh": kwh,
            "slot_color": slot_color, "credits_awarded": credits,
            "balance_after": balance}


# --------------------------------------------------------------------------
def top_up(con: sqlite3.Connection, account_id: str, cash_kes: int,
           month: str | None = None) -> dict:
    """Buy credits with cash. Atomic. Always increases the balance."""
    if cash_kes <= 0:
        raise WriteError("cash_kes must be > 0")
    credits = cash_kes * CREDITS_PER_KES
    now = _now()

    con.execute("BEGIN IMMEDIATE")
    try:
        acct = con.execute(
            "SELECT account_type, entity_id FROM minigrid_accounts WHERE account_id = ?",
            (account_id,),
        ).fetchone()
        if acct is None:
            raise UnknownAccount(account_id)

        # Apply to the account's current balance sheet (seeded demo month),
        # not the calendar month — else a later-month top-up resets the wallet.
        month = month or _latest_balance_month(con, account_id, now[:7])

        row = con.execute(
            "SELECT ending_balance_credits FROM credit_balances "
            "WHERE account_id = ? AND month = ?", (account_id, month)
        ).fetchone()
        balance = (row["ending_balance_credits"] if row else 0) + credits

        con.execute(
            """INSERT INTO billing_ledger
               (ledger_id, account_id, event_type, session_id, credits_delta,
                cash_kes, balance_after, reason, created_at)
               VALUES (?,?,'top_up',NULL,?,?,?,?,?)""",
            (_ledger_id(), account_id, credits, cash_kes, balance,
             f"top-up {cash_kes} KES", now),
        )
        if row:
            con.execute(
                """UPDATE credit_balances SET
                     ending_balance_credits = ?,
                     total_top_up_credits   = total_top_up_credits + ?,
                     cash_paid_kes          = cash_paid_kes + ?
                   WHERE account_id = ? AND month = ?""",
                (balance, credits, cash_kes, account_id, month),
            )
        else:
            con.execute(
                """INSERT INTO credit_balances
                   (account_id, account_type, entity_id, month,
                    ending_balance_credits, total_top_up_credits,
                    total_reward_credits, total_spent_credits, cash_paid_kes)
                   VALUES (?,?,?,?,?,?,0,0,?)""",
                (account_id, acct["account_type"], acct["entity_id"], month,
                 balance, credits, cash_kes),
            )
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise

    return {"account_id": account_id, "cash_kes": cash_kes,
            "credits_added": credits, "balance_after": balance}


# --------------------------------------------------------------------------
def refresh_leaderboard(con: sqlite3.Connection) -> int:
    """Rebuild the leaderboard from cooking_sessions + billing_ledger.

    Deliberately OUTSIDE the per-session transaction. Cheap enough to run on a
    timer or after each batch of sessions; safe to run concurrently with reads.

    Verified to reproduce the seeded leaderboard exactly.
    """
    con.execute("BEGIN IMMEDIATE")
    try:
        con.execute("DELETE FROM leaderboard")
        con.execute(f"""
            INSERT INTO leaderboard (
                rank, account_id, entity_id, account_type, display_name,
                leaderboard_group, sessions, kwh, green_sessions, orange_sessions,
                red_sessions, green_window_share, shifted_daytime_sessions,
                credits_earned, credits_spent, ending_balance_credits,
                cash_paid_kes, fuel_stacking_risk_days, score, privacy_level)
            SELECT
                ROW_NUMBER() OVER (ORDER BY {SCORE_SQL} DESC, account_id) AS rank,
                account_id, entity_id, account_type, display_name,
                leaderboard_group, sessions, kwh, green_sessions, orange_sessions,
                red_sessions, green_window_share, shifted_daytime_sessions,
                credits_earned, credits_spent, ending_balance_credits,
                cash_paid_kes, fuel_stacking_risk_days,
                {SCORE_SQL} AS score,
                privacy_level
            FROM (
                SELECT
                    a.account_id,
                    a.entity_id,
                    a.account_type,
                    CASE WHEN a.account_type = 'commercial'
                         THEN 'Business ' || a.entity_id
                         ELSE 'Household ' || a.entity_id END      AS display_name,
                    a.account_type                                  AS leaderboard_group,
                    COALESCE(s.n, 0)                                AS sessions,
                    ROUND(COALESCE(s.kwh, 0.0), 3)                  AS kwh,
                    COALESCE(s.g, 0)                                AS green_sessions,
                    COALESCE(s.o, 0)                                AS orange_sessions,
                    COALESCE(s.r, 0)                                AS red_sessions,
                    CASE WHEN COALESCE(s.n,0) = 0 THEN 0.0
                         ELSE ROUND(CAST(s.g AS REAL) / s.n, 3) END AS green_window_share,
                    COALESCE(s.sh, 0)                               AS shifted_daytime_sessions,
                    COALESCE(b.earned, 0)                           AS credits_earned,
                    COALESCE(b.spent, 0)                            AS credits_spent,
                    COALESCE(cb.bal, 0)                             AS ending_balance_credits,
                    COALESCE(b.cash, 0)                             AS cash_paid_kes,
                    COALESCE(f.risk_days, 0)                        AS fuel_stacking_risk_days,
                    'synthetic_id_only'                             AS privacy_level
                FROM minigrid_accounts a
                LEFT JOIN (
                    SELECT account_id, COUNT(*) n, SUM(kwh) kwh,
                           SUM(slot_color='green')  g,
                           SUM(slot_color='orange') o,
                           SUM(slot_color='red')    r,
                           SUM(shifted_daytime)     sh
                    FROM cooking_sessions GROUP BY account_id) s USING (account_id)
                LEFT JOIN (
                    SELECT account_id,
                           SUM(CASE WHEN event_type IN ('green_reward','orange_reward')
                                    THEN credits_delta ELSE 0 END) earned,
                           SUM(CASE WHEN event_type = 'cook_charge'
                                    THEN -credits_delta ELSE 0 END) spent,
                           SUM(cash_kes) cash
                    FROM billing_ledger GROUP BY account_id) b USING (account_id)
                LEFT JOIN (
                    SELECT account_id, SUM(ending_balance_credits) bal
                    FROM credit_balances GROUP BY account_id) cb USING (account_id)
                LEFT JOIN (
                    SELECT account_id, SUM(fuel_stacking_risk_flag) risk_days
                    FROM account_daily_behavior GROUP BY account_id) f USING (account_id)
            )
        """)
        n = con.execute("SELECT COUNT(*) FROM leaderboard").fetchone()[0]
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return n


# --------------------------------------------------------------------------
def assert_invariants(con: sqlite3.Connection) -> None:
    """Cheap post-condition check. Call in tests / after a demo run."""
    neg = con.execute(
        "SELECT COUNT(*) FROM credit_balances WHERE ending_balance_credits < 0"
    ).fetchone()[0]
    assert neg == 0, f"{neg} negative balances"

    drift = con.execute("""
        SELECT COUNT(*) FROM credit_balances cb
        JOIN (SELECT account_id, SUM(credits_delta) net
              FROM billing_ledger GROUP BY account_id) b USING (account_id)
        WHERE cb.ending_balance_credits <> b.net
    """).fetchone()[0]
    assert drift == 0, f"{drift} accounts where balance != sum(ledger)"

    fk = con.execute("PRAGMA foreign_key_check").fetchall()
    assert not fk, f"FK violations: {fk[:3]}"
