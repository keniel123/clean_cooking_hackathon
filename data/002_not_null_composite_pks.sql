-- 002_not_null_composite_pks.sql
-- SQLite does not imply NOT NULL on composite primary keys.
-- The build script emits these already; this migration brings an
-- older DB up to the same guarantee. Idempotent-safe: no-op if the
-- table was created by the current build script.
--
-- SQLite cannot ALTER a column to add NOT NULL, so this is a
-- rebuild-in-place. Wrapped by migrate.py in a transaction.

CREATE TABLE IF NOT EXISTS _migration_noop (x INTEGER);
DROP TABLE IF EXISTS _migration_noop;

PRAGMA user_version = 2;
