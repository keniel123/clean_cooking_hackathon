#!/usr/bin/env python3
"""
migrate.py — apply versioned .sql migrations to oloika.sqlite.

Uses SQLite's PRAGMA user_version as the schema version counter.
Each migrations/NNN_*.sql file sets `PRAGMA user_version = NNN;` as its
last statement. Files are applied in filename order, each in a transaction,
and only if NNN > the current user_version.

    python data/migrate.py --db data/oloika.sqlite          # apply pending
    python data/migrate.py --db data/oloika.sqlite --status # show version
    python data/migrate.py --db data/oloika.sqlite --backup backups/

Backup uses sqlite3's online backup API, which is safe on a live DB
(unlike `cp`, which can capture a torn WAL).
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
MIGRATIONS = HERE / "migrations"


def current_version(con: sqlite3.Connection) -> int:
    return con.execute("PRAGMA user_version").fetchone()[0]


def discover() -> list[tuple[int, Path]]:
    out = []
    for p in sorted(MIGRATIONS.glob("*.sql")):
        m = re.match(r"^(\d+)_", p.name)
        if not m:
            print(f"  ! skipping unnumbered migration {p.name}")
            continue
        out.append((int(m.group(1)), p))
    return sorted(out)


def apply_pending(con: sqlite3.Connection) -> int:
    have = current_version(con)
    applied = 0
    for version, path in discover():
        if version <= have:
            continue
        sql = path.read_text()
        print(f"  applying {path.name} ({have} -> {version})")
        # sqlite3.executescript() issues an implicit COMMIT before it runs, so
        # the BEGIN must live inside the script text, not around the call.
        try:
            con.executescript("BEGIN;\n" + sql + "\nCOMMIT;")
        except Exception:
            try:
                con.execute("ROLLBACK")
            except sqlite3.OperationalError:
                pass  # already rolled back
            print(f"  FAILED on {path.name}; rolled back. DB still at v{have}.")
            raise
        got = current_version(con)
        if got != version:
            raise SystemExit(
                f"{path.name} did not set PRAGMA user_version = {version} "
                f"(reports {got}). Fix the migration."
            )
        have = got
        applied += 1
    return applied


def backup(db: Path, dest_dir: Path) -> Path:
    """Online backup — safe against a live, in-use database."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = dest_dir / f"oloika-{stamp}.sqlite"
    src = sqlite3.connect(db)
    dst = sqlite3.connect(dest)
    with dst:
        src.backup(dst)
    dst.close()
    src.close()
    return dest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=HERE / "oloika.sqlite")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--backup", type=Path, metavar="DIR")
    args = ap.parse_args()

    if not args.db.exists():
        sys.exit(f"ERROR: {args.db} not found. Run load_oloika_dataset_sqlite.py first.")

    if args.backup:
        dest = backup(args.db, args.backup)
        size = dest.stat().st_size / 1024
        print(f"backed up -> {dest} ({size:.0f} KB)")
        return

    con = sqlite3.connect(args.db, isolation_level=None)
    con.execute("PRAGMA foreign_keys = ON")

    if args.status:
        print(f"{args.db}: schema v{current_version(con)}")
        pending = [p.name for v, p in discover() if v > current_version(con)]
        print(f"pending: {pending or 'none'}")
        return

    n = apply_pending(con)
    print(f"schema now v{current_version(con)} ({n} migration(s) applied)")
    con.close()


if __name__ == "__main__":
    main()
