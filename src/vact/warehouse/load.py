"""MERGE-style loads into the DuckDB warehouse."""

from __future__ import annotations

from pathlib import Path

import duckdb

from vact.models.legislators import DimLegislatorRow
from vact.warehouse.connection import apply_sql_file, connect

_UPSERT_SQL = """
INSERT INTO dim_legislator AS t (
    bioguide_id,
    govtrack_id,
    icpsr_id,
    lis_id,
    full_name,
    chamber,
    state,
    district_current,
    party,
    term_start,
    term_end,
    first_elected,
    is_incumbent,
    website
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (bioguide_id, term_start) DO UPDATE SET
    govtrack_id = excluded.govtrack_id,
    icpsr_id = excluded.icpsr_id,
    lis_id = excluded.lis_id,
    full_name = excluded.full_name,
    chamber = excluded.chamber,
    state = excluded.state,
    district_current = excluded.district_current,
    party = excluded.party,
    term_end = excluded.term_end,
    first_elected = excluded.first_elected,
    is_incumbent = excluded.is_incumbent,
    website = excluded.website
"""


def ensure_dim_legislator(conn: duckdb.DuckDBPyConnection) -> None:
    apply_sql_file(conn, "ddl_dim_legislator.sql")


def upsert_dim_legislator(
    rows: list[DimLegislatorRow],
    *,
    conn: duckdb.DuckDBPyConnection | None = None,
    warehouse_path: Path | None = None,
) -> int:
    """
    Upsert SCD2 legislator rows on (bioguide_id, term_start).

    Idempotent: re-loading the same natural keys updates in place.
    """
    owns_conn = conn is None
    db = conn or connect(warehouse_path)
    try:
        ensure_dim_legislator(db)
        if not rows:
            return 0

        payload = [
            (
                row.bioguide_id,
                row.govtrack_id,
                row.icpsr_id,
                row.lis_id,
                row.full_name,
                row.chamber,
                row.state,
                row.district_current,
                row.party,
                row.term_start,
                row.term_end,
                row.first_elected,
                row.is_incumbent,
                row.website,
            )
            for row in rows
        ]
        db.executemany(_UPSERT_SQL, payload)
        return len(rows)
    finally:
        if owns_conn:
            db.close()
