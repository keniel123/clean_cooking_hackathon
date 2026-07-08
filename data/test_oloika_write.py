#!/usr/bin/env python3
"""Tests for oloika_write.py. Run against a throwaway copy of oloika.sqlite."""
import shutil, sqlite3, sys, os
sys.path.insert(0, os.path.dirname(__file__))
import oloika_write as W

SRC = "repo/data/oloika.sqlite"
DB = "/tmp/test_oloika.sqlite"

def fresh():
    for suf in ("", "-wal", "-shm"):
        p = DB + suf
        if os.path.exists(p): os.remove(p)
    shutil.copy(SRC, DB)
    return W.connect(DB)

def snapshot(con):
    return (
        con.execute("SELECT COUNT(*) FROM billing_ledger").fetchone()[0],
        con.execute("SELECT COALESCE(SUM(ending_balance_credits),0) FROM credit_balances").fetchone()[0],
        con.execute("SELECT COUNT(*) FROM cooking_sessions").fetchone()[0],
    )

fails = []
def check(name, cond, extra=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name} {extra}")
    if not cond: fails.append(name)

# ---------------------------------------------------------------- 1
print("\n[1] refresh_leaderboard reproduces the seeded leaderboard exactly")
con = fresh()
before = con.execute("SELECT account_id,sessions,kwh,green_sessions,orange_sessions,"
                     "red_sessions,shifted_daytime_sessions,credits_earned,credits_spent,"
                     "ending_balance_credits,cash_paid_kes,fuel_stacking_risk_days,score "
                     "FROM leaderboard ORDER BY account_id").fetchall()
n = W.refresh_leaderboard(con)
after = con.execute("SELECT account_id,sessions,kwh,green_sessions,orange_sessions,"
                    "red_sessions,shifted_daytime_sessions,credits_earned,credits_spent,"
                    "ending_balance_credits,cash_paid_kes,fuel_stacking_risk_days,score "
                    "FROM leaderboard ORDER BY account_id").fetchall()
check("row count preserved", len(before) == len(after) == 84, f"({n})")
diffs = [(tuple(a), tuple(b)) for a, b in zip(before, after) if tuple(a) != tuple(b)]
check("every column identical", not diffs, f"({len(diffs)} differing rows)")
if diffs:
    for a, b in diffs[:3]:
        print("      seed:", a); print("      calc:", b)

# rank ordering must be consistent with score desc
ranks = con.execute("SELECT rank, score FROM leaderboard ORDER BY rank").fetchall()
check("rank monotonic in score", all(ranks[i]["score"] >= ranks[i+1]["score"]
                                    for i in range(len(ranks)-1)))
con.close()

# ---------------------------------------------------------------- 2
print("\n[2] complete_session is atomic + guard rejects overdraw")
con = fresh()
acct = con.execute("SELECT account_id FROM credit_balances ORDER BY ending_balance_credits LIMIT 1").fetchone()[0]
bal = con.execute("SELECT ending_balance_credits FROM credit_balances WHERE account_id=?", (acct,)).fetchone()[0]
snap = snapshot(con)
# a cook far bigger than the balance can afford
huge_kwh = (bal / W.CREDITS_PER_KWH_CHARGE) + 100
try:
    W.complete_session(con, "SESS-OVERDRAW", acct, huge_kwh, "red")
    check("overdraw rejected", False, "(no exception raised!)")
except W.InsufficientCredits as e:
    check("overdraw rejected", True, f"(balance {e.balance} < {e.needed})")
check("nothing written on rollback", snapshot(con) == snap)
check("balance unchanged", con.execute(
    "SELECT ending_balance_credits FROM credit_balances WHERE account_id=?", (acct,)
).fetchone()[0] == bal)
con.close()

# ---------------------------------------------------------------- 3
print("\n[3] happy path: green session charges, rewards, updates balance")
con = fresh()
acct = con.execute("SELECT account_id FROM credit_balances ORDER BY ending_balance_credits DESC LIMIT 1").fetchone()[0]
bal0 = con.execute("SELECT ending_balance_credits FROM credit_balances WHERE account_id=?", (acct,)).fetchone()[0]
res = W.complete_session(con, "SESS-NEW-1", acct, 1.000, "green", start_at="2025-06-15T12:00:00")
exp_charge = round(1.0 * W.CREDITS_PER_KWH_CHARGE)
exp_reward = round(1.0 * W.GREEN_REWARD_PER_KWH)
check("charge correct", res["credits_charged"] == exp_charge, f"({res['credits_charged']})")
check("reward correct", res["credits_rewarded"] == exp_reward, f"({res['credits_rewarded']})")
bal1 = con.execute("SELECT ending_balance_credits FROM credit_balances WHERE account_id=?", (acct,)).fetchone()[0]
check("balance = bal0 - charge + reward", bal1 == bal0 - exp_charge + exp_reward, f"({bal0}->{bal1})")
check("two ledger rows for session", con.execute(
    "SELECT COUNT(*) FROM billing_ledger WHERE session_id='SESS-NEW-1'").fetchone()[0] == 2)
check("ledger balance_after matches", con.execute(
    "SELECT balance_after FROM billing_ledger WHERE session_id='SESS-NEW-1' "
    "ORDER BY rowid DESC LIMIT 1").fetchone()[0] == bal1)

# red session earns nothing
res_r = W.complete_session(con, "SESS-NEW-2", acct, 1.000, "red", start_at="2025-06-15T20:00:00")
check("red reward is zero", res_r["credits_rewarded"] == 0)
check("red writes one ledger row", con.execute(
    "SELECT COUNT(*) FROM billing_ledger WHERE session_id='SESS-NEW-2'").fetchone()[0] == 1)
W.assert_invariants(con)
check("invariants hold after writes", True)
con.close()

# ---------------------------------------------------------------- 4
print("\n[4] idempotency: replaying a session does not double-charge")
con = fresh()
acct = con.execute("SELECT account_id FROM credit_balances ORDER BY ending_balance_credits DESC LIMIT 1").fetchone()[0]
W.complete_session(con, "SESS-DUP", acct, 0.5, "green", start_at="2025-06-15T12:00:00")
snap = snapshot(con)
try:
    W.complete_session(con, "SESS-DUP", acct, 0.5, "green", start_at="2025-06-15T12:00:00")
    check("replay rejected", False, "(no exception!)")
except W.SessionAlreadyBilled:
    check("replay rejected", True)
check("no rows added on replay", snapshot(con) == snap)
con.close()

# ---------------------------------------------------------------- 5
print("\n[5] top_up increases balance and is reflected in ledger")
con = fresh()
acct = "HH-0020"
b0 = con.execute("SELECT ending_balance_credits FROM credit_balances WHERE account_id=?", (acct,)).fetchone()[0]
r = W.top_up(con, acct, 100, month="2025-06")
check("credits = cash * rate", r["credits_added"] == 100 * W.CREDITS_PER_KES)
b1 = con.execute("SELECT ending_balance_credits FROM credit_balances WHERE account_id=?", (acct,)).fetchone()[0]
check("balance increased", b1 == b0 + 100 * W.CREDITS_PER_KES, f"({b0}->{b1})")
W.assert_invariants(con)
check("invariants hold after top_up", True)
con.close()

# ---------------------------------------------------------------- 6
print("\n[6] unknown account rejected, bad slot_color rejected")
con = fresh()
try:
    W.complete_session(con, "S-X", "NOPE-999", 1.0, "green"); check("unknown account", False)
except W.UnknownAccount: check("unknown account rejected", True)
try:
    W.complete_session(con, "S-Y", "HH-0020", 1.0, "purple"); check("bad slot", False)
except W.WriteError: check("bad slot_color rejected", True)
con.close()

# ---------------------------------------------------------------- 7
print("\n[7] end-to-end: sessions then refresh -> leaderboard still consistent")
con = fresh()
acct = "HH-0020"
for i in range(5):
    try:
        W.complete_session(con, f"SESS-E2E-{i}", acct, 0.3, "green",
                           start_at="2025-06-20T11:00:00", shifted_daytime=1)
    except W.WriteError as e:
        print("     write error:", e)
W.refresh_leaderboard(con)
W.assert_invariants(con)
row = con.execute("SELECT sessions, green_sessions, score FROM leaderboard WHERE account_id=?", (acct,)).fetchone()
sess = con.execute("SELECT COUNT(*) FROM cooking_sessions WHERE account_id=?", (acct,)).fetchone()[0]
check("leaderboard sessions == cooking_sessions", row["sessions"] == sess, f"({row['sessions']} vs {sess})")
bad = con.execute(f"SELECT COUNT(*) FROM leaderboard WHERE score <> {W.SCORE_SQL}").fetchone()[0]
check("score formula holds post-refresh", bad == 0)
con.close()

# ---------------------------------------------------------------- 8
print("\n[8] concurrent writers (WAL + busy_timeout) do not corrupt or deadlock")
import threading
con = fresh(); con.close()
errors = []
def worker(k):
    try:
        c = W.connect(DB)
        for i in range(10):
            try:
                W.complete_session(c, f"SESS-T{k}-{i}", "BIZ-005", 0.1, "green",
                                   start_at="2025-06-21T12:00:00")
            except W.WriteError:
                pass
        c.close()
    except Exception as e:
        errors.append(repr(e))
ts = [threading.Thread(target=worker, args=(k,)) for k in range(4)]
[t.start() for t in ts]; [t.join() for t in ts]
check("no exceptions from concurrent writers", not errors, str(errors[:2]))
con = W.connect(DB)
W.assert_invariants(con)
check("invariants hold after concurrency", True)
written = con.execute("SELECT COUNT(*) FROM billing_ledger WHERE session_id LIKE 'SESS-T%'").fetchone()[0]
check("all 40 sessions billed exactly once", written == 80, f"(2 rows x 40 = {written})")
con.close()

print("\n" + ("ALL PASS" if not fails else f"FAILURES: {fails}"))
sys.exit(1 if fails else 0)
