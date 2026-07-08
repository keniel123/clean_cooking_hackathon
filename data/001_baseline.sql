-- 001_baseline.sql
-- Baseline. The schema at this version is whatever
-- data/load_oloika_dataset_sqlite.py produces from data/synthetic/*.csv.
-- Recorded here so later migrations have a known starting point.
--
-- Apply with:  python data/migrate.py
PRAGMA user_version = 1;
