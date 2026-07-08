"""
Builds oloika.sqlite from the synthetic Oloika CSV data.

Creates typed tables with primary keys, foreign keys and indexes.
"""

from __future__ import annotations
import csv
import json
import sqlite3
from pathlib import Path

DATA = Path(__file__).parent / "synthetic"
SCHEMA_JSON = DATA / "oloika_dataset_schema.json"
OUT = Path(__file__).parent / "oloika.sqlite"

# Create a mapping from CSV file names to table names:
TABLES = {
    "oloika_people.csv": "people",
    "oloika_households.csv": "households",
    "oloika_commercial_profiles.csv": "commercial_profiles",
    "oloika_minigrid_accounts.csv": "minigrid_accounts",
    "oloika_cooker_assets.csv": "cooker_assets",
    "oloika_credit_balances_june_2025.csv": "credit_balances",
    "oloika_leaderboard_june_2025.csv": "leaderboard",
    "oloika_grid_hourly_june_2025.csv": "grid_hourly",
    "oloika_cooking_sessions_june_2025.csv": "cooking_sessions",
    "oloika_account_daily_behavior_june_2025.csv": "account_daily_behavior",
    "oloika_cooker_utilization_daily_june_2025.csv": "cooker_utilization_daily",
    "oloika_billing_ledger_june_2025.csv": "billing_ledger",
}

# Primary keys:
EXTRA_PK = {
    "people": ["person_id"],
    "households": ["household_id"],
    "commercial_profiles": ["business_id"],
    "minigrid_accounts": ["account_id"],
}

# Foreign keys:
EXTRA_FK = {
    "households": {"head_person_id": ("people", "person_id")},
    "commercial_profiles": {"owner_person_id": ("people", "person_id")},
}

# Infer the type of a column from its values:

def infer_type(values: list[str]) -> str:
    seen_int = seen_float = has_value = False
    for v in values:
        if v == "" or v is None:
            continue
        has_value = True
        low = v.strip().lower()
        if low in ("true", "false"):
            return "INTEGER"  # store booleans as 0/1
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


def coerce(value: str, col_type: str):
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
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)
    return header, rows


def main():
    schema = {}
    if SCHEMA_JSON.exists():
        schema = json.loads(SCHEMA_JSON.read_text())["files"]

    if OUT.exists():
        OUT.unlink()
    con = sqlite3.connect(OUT)
    con.execute("PRAGMA foreign_keys = ON")

    table_meta = {}  # table -> (header, col_types, pk, fks)

    # First pass: read all CSVs, infer types, decide PK/FK
    for csv_name, table in TABLES.items():
        header, rows = read_csv(DATA / csv_name)
        col_types = {}
        for i, col in enumerate(header):
            col_types[col] = infer_type([r[i] for r in rows if i < len(r)])

        meta = schema.get(csv_name, {})
        pk = meta.get("primary_key") or EXTRA_PK.get(table, [])

        fks = {}
        for col, target in (meta.get("foreign_keys") or {}).items():
            # target like "oloika_minigrid_accounts.csv.account_id"
            tgt_csv, tgt_col = target.rsplit(".", 1)
            tgt_csv = tgt_csv if tgt_csv.endswith(".csv") else tgt_csv + ".csv"
            tgt_table = TABLES.get(tgt_csv)
            if tgt_table:
                fks[col] = (tgt_table, tgt_col)
        for col, (t, c) in EXTRA_FK.get(table, {}).items():
            fks[col] = (t, c)

        table_meta[table] = (header, col_types, pk, fks, rows)

    # Drop FKs whose referenced value set doesn't fully cover child values,
    # so a legitimately-loose synthetic dataset still loads cleanly.
    key_sets = {}
    for table, (header, col_types, pk, fks, rows) in table_meta.items():
        key_sets[table] = {}
    for table, (header, col_types, pk, fks, rows) in table_meta.items():
        for col in header:
            idx = header.index(col)
            key_sets[table][col] = {r[idx] for r in rows if idx < len(r) and r[idx] != ""}

    for table, (header, col_types, pk, fks, rows) in table_meta.items():
        valid = {}
        for col, (tgt_table, tgt_col) in fks.items():
            child = key_sets[table].get(col, set())
            parent = key_sets.get(tgt_table, {}).get(tgt_col, set())
            if child <= parent:
                valid[col] = (tgt_table, tgt_col)
            else:
                missing = len(child - parent)
                print(f"  ! skipping FK {table}.{col} -> {tgt_table}.{tgt_col} "
                      f"({missing} unmatched values)")
        table_meta[table] = (header, col_types, pk, valid, rows)

    # Order tables so parents are created/loaded before children
    order = [
        "people", "households", "commercial_profiles", "minigrid_accounts",
        "cooker_assets", "cooking_sessions", "credit_balances", "leaderboard",
        "grid_hourly", "account_daily_behavior", "cooker_utilization_daily",
        "billing_ledger",
    ]

    # Create tables
    for table in order:
        header, col_types, pk, fks, rows = table_meta[table]
        cols_sql = []
        for col in header:
            line = f'"{col}" {col_types[col]}'
            if pk == [col]:
                line += " PRIMARY KEY"
            cols_sql.append(line)
        constraints = []
        if len(pk) > 1:
            constraints.append("PRIMARY KEY (" + ", ".join(f'"{c}"' for c in pk) + ")")
        for col, (tgt_table, tgt_col) in fks.items():
            constraints.append(
                f'FOREIGN KEY ("{col}") REFERENCES "{tgt_table}"("{tgt_col}")'
            )
        body = ",\n  ".join(cols_sql + constraints)
        con.execute(f'CREATE TABLE "{table}" (\n  {body}\n)')

    # Load data
    for table in order:
        header, col_types, pk, fks, rows = table_meta[table]
        placeholders = ", ".join(["?"] * len(header))
        cols = ", ".join(f'"{c}"' for c in header)
        typed_rows = []
        for r in rows:
            r = list(r) + [None] * (len(header) - len(r))
            typed_rows.append(
                tuple(coerce(r[i], col_types[header[i]]) for i in range(len(header)))
            )
        con.executemany(
            f'INSERT INTO "{table}" ({cols}) VALUES ({placeholders})', typed_rows
        )
        print(f"  loaded {table}: {len(typed_rows)} rows")

    # Helpful indexes on common join / filter columns
    index_cols = {
        "cooking_sessions": ["account_id", "cooker_id", "date"],
        "billing_ledger": ["account_id", "session_id", "event_type"],
        "account_daily_behavior": ["account_id", "date"],
        "cooker_utilization_daily": ["cooker_id", "date"],
        "cooker_assets": ["account_id"],
        "minigrid_accounts": ["entity_id", "community_id"],
        "credit_balances": ["account_id"],
        "leaderboard": ["account_id"],
        "people": ["household_id"],
        "grid_hourly": ["date"],
    }
    for table, cols in index_cols.items():
        existing = {row[1] for row in con.execute(f'PRAGMA table_info("{table}")')}
        for col in cols:
            if col in existing:
                con.execute(
                    f'CREATE INDEX "idx_{table}_{col}" ON "{table}"("{col}")'
                )

    con.commit()

    # Integrity check
    problems = con.execute("PRAGMA foreign_key_check").fetchall()
    if problems:
        print("  FK violations:", problems[:10])
    else:
        print("  foreign_key_check: OK")

    con.close()
    print(f"\nDatabase written to {OUT} ({OUT.stat().st_size/1024:.0f} KB)")


if __name__ == "__main__":
    main()