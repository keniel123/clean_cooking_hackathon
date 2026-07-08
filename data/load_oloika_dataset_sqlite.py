#!/usr/bin/env python3
"""
load_oloika_dataset_sqlite.py — build the canonical oloika.sqlite from data/synthetic/*.csv

Reproducible: drops and rebuilds the database from CSV, applying primary keys,
foreign keys, column types, and the indexes the API filters on.

Usage
-----
    python data/load_oloika_dataset_sqlite.py                  # build in place
    python data/load_oloika_dataset_sqlite.py --out /data/oloika.sqlite
    python data/load_oloika_dataset_sqlite.py --check          # verify only, no write

Paths default to being relative to this file, so it works in a checkout and in CI.
Requires only the stdlib (no pandas).
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_DATA = HERE / "synthetic"
DEFAULT_OUT = HERE / "oloika.sqlite"
SCHEMA_JSON_NAME = "oloika_dataset_schema.json"

# --------------------------------------------------------------------------
# CSV file -> table name.  Order matters: parents before children (FK load order).
# --------------------------------------------------------------------------
TABLES: dict[str, str] = {
    "oloika_people.csv": "people",
    "oloika_households.csv": "households",
    "oloika_commercial_profiles.csv": "commercial_profiles",
    "oloika_minigrid_accounts.csv": "minigrid_accounts",
    "oloika_cooker_assets.csv": "cooker_assets",
    "oloika_cooking_sessions_june_2025.csv": "cooking_sessions",
    "oloika_credit_balances_june_2025.csv": "credit_balances",
    "oloika_leaderboard_june_2025.csv": "leaderboard",
    "oloika_grid_hourly_june_2025.csv": "grid_hourly",
    "oloika_account_daily_behavior_june_2025.csv": "account_daily_behavior",
    "oloika_cooker_utilization_daily_june_2025.csv": "cooker_utilization_daily",
    "oloika_billing_ledger_june_2025.csv": "billing_ledger",
}
LOAD_ORDER = list(TABLES.values())

# Primary keys for the four files not described in oloika_dataset_schema.json.
EXTRA_PK = {
    "people": ["person_id"],
    "households": ["household_id"],
    "commercial_profiles": ["business_id"],
    "minigrid_accounts": ["account_id"],
}

# Foreign keys not described in the schema JSON.
# NOTE: minigrid_accounts.entity_id is polymorphic (household OR business),
# so it deliberately carries no FK constraint.
EXTRA_FK = {
    "households": {"head_person_id": ("people", "person_id")},
    "commercial_profiles": {"owner_person_id": ("people", "person_id")},
}

# Columns the API filters/joins on. Everything the brief asked for, plus the
# join keys. Composite indexes first — they also serve the leading column.
INDEXES: dict[str, list[list[str]]] = {
    "cooking_sessions": [
        ["account_id", "date"],
        ["cooker_id", "date"],
        ["slot_color"],
        ["date"],
        ["start_hour_eat"],
        ["session_id"],  # redundant w/ PK but harmless; kept explicit for the API
    ],
    "grid_hourly": [
        ["date", "hour_eat"],
        ["slot_color"],
        ["hour_eat"],
    ],
    "billing_ledger": [
        ["account_id", "created_at"],
        ["session_id"],
        ["event_type"],
    ],
    "account_daily_behavior": [["account_id", "date"], ["date"]],
    "cooker_utilization_daily": [["cooker_id", "date"], ["account_id"], ["date"]],
    "cooker_assets": [["account_id"], ["plug"]],
    "minigrid_accounts": [["entity_id"], ["community_id"], ["account_type"]],
    "credit_balances": [["account_id"]],
    "leaderboard": [["account_id"], ["leaderboard_group", "rank"], ["score"]],
    "people": [["household_id"]],
    "households": [["head_person_id"]],
}

# Columns that must never be NULL. SQLite does not imply NOT NULL on
# composite primary keys, so state it explicitly.
NOT_NULL: dict[str, set[str]] = {
    "account_daily_behavior": {"account_id", "date"},
    "cooker_utilization_daily": {"cooker_id", "date"},
    "credit_balances": {"account_id", "month"},
    "billing_ledger": {"ledger_id", "account_id", "event_type"},
    "cooking_sessions": {"session_id", "account_id"},
}

# Ledger event types the write path understands.
LEDGER_EVENT_TYPES = ("top_up", "green_reward", "orange_reward", "cook_charge")


# --------------------------------------------------------------------------
# type inference
# --------------------------------------------------------------------------
def infer_type(values) -> str:
    seen_int = seen_float = has_value = False
    for v in values:
        if v == "" or v is None:
            continue
        has_value = True
        low = v.strip().lower()
        if low in ("true", "false"):
            return "INTEGER"  # booleans stored 0/1
        try:
            int(v)
            seen_int = True
            continue
        except ValueError:
            pass
        try:
            float(v)
            seen_float = True
            continue
        except ValueError:
            return "TEXT"
    if not has_value:
        return "TEXT"
    if seen_float:
        return "REAL"
    if seen_int:
        return "INTEGER"
    return "TEXT"


def coerce(value, col_type):
    if value == "" or value is None:
        return None
    if col_type == "INTEGER":
        low = value.strip().lower()
        if low == "true":
            return 1
        if low == "false":
            return 0
        return int(value)
    if col_type == "REAL":
        return float(value)
    return value


def read_csv(path: Path):
    if not path.exists():
        sys.exit(
            f"ERROR: missing CSV {path}\n"
            f"       The synthetic CSVs may be gitignored. Restore data/synthetic/ "
            f"before building."
        )
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = [r for r in reader if any(c.strip() for c in r)]
    return header, rows


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------
def build(data_dir: Path, out: Path) -> sqlite3.Connection:
    schema_path = data_dir / SCHEMA_JSON_NAME
    schema = json.loads(schema_path.read_text())["files"] if schema_path.exists() else {}

    # ---- read every CSV, infer types, resolve keys
    meta = {}
    for csv_name, table in TABLES.items():
        header, rows = read_csv(data_dir / csv_name)
        col_types = {
            col: infer_type([r[i] for r in rows if i < len(r)])
            for i, col in enumerate(header)
        }
        spec = schema.get(csv_name, {})
        pk = spec.get("primary_key") or EXTRA_PK.get(table, [])

        fks = {}
        for col, target in (spec.get("foreign_keys") or {}).items():
            tgt_csv, tgt_col = target.rsplit(".", 1)
            if not tgt_csv.endswith(".csv"):
                tgt_csv += ".csv"
            if tgt_csv in TABLES:
                fks[col] = (TABLES[tgt_csv], tgt_col)
        fks.update(EXTRA_FK.get(table, {}))
        meta[table] = dict(header=header, types=col_types, pk=pk, fks=fks, rows=rows)

    # ---- drop FKs whose child values aren't fully covered by the parent,
    #      so a loose synthetic dataset still loads (and we say so out loud).
    keysets = {
        t: {c: {r[i] for r in m["rows"] if i < len(r) and r[i] != ""}
            for i, c in enumerate(m["header"])}
        for t, m in meta.items()
    }
    for table, m in meta.items():
        kept = {}
        for col, (tt, tc) in m["fks"].items():
            child = keysets[table].get(col, set())
            parent = keysets.get(tt, {}).get(tc, set())
            if child <= parent:
                kept[col] = (tt, tc)
            else:
                print(f"  ! dropping FK {table}.{col} -> {tt}.{tc} "
                      f"({len(child - parent)} unmatched values)")
        m["fks"] = kept

    if out.exists():
        out.unlink()
    out.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(out)
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")   # concurrent readers + one writer
    con.execute("PRAGMA synchronous = NORMAL")

    # ---- DDL
    for table in LOAD_ORDER:
        m = meta[table]
        header, types, pk, fks = m["header"], m["types"], m["pk"], m["fks"]
        nn = NOT_NULL.get(table, set())
        cols, constraints = [], []
        for col in header:
            line = f'"{col}" {types[col]}'
            if pk == [col]:
                line += " PRIMARY KEY"
            if col in nn and pk != [col]:
                line += " NOT NULL"
            cols.append(line)
        if len(pk) > 1:
            constraints.append("PRIMARY KEY (" + ", ".join(f'"{c}"' for c in pk) + ")")
        for col, (tt, tc) in sorted(fks.items()):
            constraints.append(f'FOREIGN KEY ("{col}") REFERENCES "{tt}"("{tc}")')
        if table == "billing_ledger":
            constraints.append(
                "CHECK (event_type IN ('" + "', '".join(LEDGER_EVENT_TYPES) + "'))"
            )
            constraints.append("CHECK (balance_after >= 0)")
        if table == "credit_balances":
            constraints.append("CHECK (ending_balance_credits >= 0)")
        body = ",\n  ".join(cols + constraints)
        con.execute(f'CREATE TABLE "{table}" (\n  {body}\n)')

    # ---- load
    for table in LOAD_ORDER:
        m = meta[table]
        header, types, rows = m["header"], m["types"], m["rows"]
        placeholders = ", ".join("?" * len(header))
        collist = ", ".join(f'"{c}"' for c in header)
        typed = []
        for r in rows:
            r = list(r) + [None] * (len(header) - len(r))
            typed.append(tuple(coerce(r[i], types[header[i]]) for i in range(len(header))))
        con.executemany(
            f'INSERT INTO "{table}" ({collist}) VALUES ({placeholders})', typed
        )
        print(f"  loaded {table:28s} {len(typed):>5d} rows")

    # ---- indexes
    n_idx = 0
    for table, specs in INDEXES.items():
        existing = {row[1] for row in con.execute(f'PRAGMA table_info("{table}")')}
        for colset in specs:
            if not all(c in existing for c in colset):
                continue
            name = f"idx_{table}_" + "_".join(colset)
            cols = ", ".join(f'"{c}"' for c in colset)
            con.execute(f'CREATE INDEX IF NOT EXISTS "{name}" ON "{table}"({cols})')
            n_idx += 1
    print(f"  created {n_idx} indexes")

    con.commit()
    con.execute("ANALYZE")
    con.commit()
    return con


# --------------------------------------------------------------------------
# integrity checks — fail loudly rather than ship a bad DB
# --------------------------------------------------------------------------
def check(con: sqlite3.Connection) -> bool:
    ok = True

    fk = con.execute("PRAGMA foreign_key_check").fetchall()
    if fk:
        ok = False
        print(f"  FAIL foreign_key_check: {len(fk)} violations, e.g. {fk[:3]}")
    else:
        print("  ok   foreign_key_check")

    integ = con.execute("PRAGMA integrity_check").fetchone()[0]
    print(f"  {'ok  ' if integ == 'ok' else 'FAIL'} integrity_check: {integ}")
    ok &= integ == "ok"

    # credit_balances must equal the net of the ledger
    bad = con.execute("""
        SELECT COUNT(*) FROM credit_balances cb
        JOIN (SELECT account_id, SUM(credits_delta) net
              FROM billing_ledger GROUP BY account_id) b USING (account_id)
        WHERE cb.ending_balance_credits <> b.net
    """).fetchone()[0]
    print(f"  {'ok  ' if not bad else 'FAIL'} credit_balances == sum(ledger.credits_delta)  [{bad} bad]")
    ok &= bad == 0

    # leaderboard must be derivable from sessions + ledger
    bad = con.execute("""
        SELECT COUNT(*) FROM leaderboard l
        JOIN (SELECT account_id, COUNT(*) n,
                     SUM(slot_color='green')  g,
                     SUM(slot_color='orange') o,
                     SUM(slot_color='red')    r,
                     SUM(shifted_daytime)     sh
              FROM cooking_sessions GROUP BY account_id) s USING (account_id)
        WHERE l.sessions <> s.n OR l.green_sessions <> s.g
           OR l.orange_sessions <> s.o OR l.red_sessions <> s.r
           OR l.shifted_daytime_sessions <> s.sh
    """).fetchone()[0]
    print(f"  {'ok  ' if not bad else 'FAIL'} leaderboard == agg(cooking_sessions)  [{bad} bad]")
    ok &= bad == 0

    # score formula (exact, verified against the seed)
    bad = con.execute("""
        SELECT COUNT(*) FROM leaderboard
        WHERE score <> credits_earned + 5*green_sessions + 1*orange_sessions
                       - 5*red_sessions + 8*shifted_daytime_sessions + sessions
    """).fetchone()[0]
    print(f"  {'ok  ' if not bad else 'FAIL'} leaderboard.score formula  [{bad} bad]")
    ok &= bad == 0

    neg = con.execute(
        "SELECT COUNT(*) FROM credit_balances WHERE ending_balance_credits < 0"
    ).fetchone()[0]
    print(f"  {'ok  ' if not neg else 'FAIL'} no negative balances  [{neg} bad]")
    ok &= neg == 0

    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=DEFAULT_DATA,
                    help=f"directory of source CSVs (default: {DEFAULT_DATA})")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT,
                    help=f"output sqlite path (default: {DEFAULT_OUT})")
    ap.add_argument("--check", action="store_true",
                    help="only run integrity checks against an existing --out")
    args = ap.parse_args()

    if args.check:
        if not args.out.exists():
            sys.exit(f"ERROR: {args.out} does not exist")
        con = sqlite3.connect(args.out)
        con.execute("PRAGMA foreign_keys = ON")
        print(f"Checking {args.out}")
        sys.exit(0 if check(con) else 1)

    print(f"Building {args.out} from {args.data}")
    con = build(args.data, args.out)
    print("\nIntegrity:")
    ok = check(con)
    con.close()
    size = args.out.stat().st_size / 1024
    print(f"\n{'OK' if ok else 'FAILED'} — {args.out} ({size:.0f} KB)")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
