-- Idempotent migrations for existing warehouse files created before kit alignment.

-- Rename lis_id -> lis_member_id when the legacy column is present.
CREATE OR REPLACE MACRO _vact_has_column(tbl, col) AS (
    EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = tbl AND column_name = col
    )
);

-- DuckDB lacks IF ALTER in older versions; apply via Python helper instead.
-- This file documents intended migration state. See warehouse/migrate.py.
