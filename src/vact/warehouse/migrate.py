"""Idempotent warehouse migrations for kit alignment."""

from __future__ import annotations

import duckdb


def _columns(conn: duckdb.DuckDBPyConnection, table: str) -> set[str]:
    rows = conn.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = ?
        """,
        [table],
    ).fetchall()
    return {r[0] for r in rows}


def apply_migrations(conn: duckdb.DuckDBPyConnection) -> None:
    """Bring an existing warehouse forward without TRUNCATE."""
    tables = {
        r[0]
        for r in conn.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'main'
            """
        ).fetchall()
    }

    if "dim_legislator" in tables:
        cols = _columns(conn, "dim_legislator")
        if "lis_id" in cols and "lis_member_id" not in cols:
            conn.execute(
                "ALTER TABLE dim_legislator RENAME COLUMN lis_id TO lis_member_id"
            )
        if "district_2025" not in cols:
            conn.execute("ALTER TABLE dim_legislator ADD COLUMN district_2025 INTEGER")
        if "district_2026" not in cols:
            conn.execute("ALTER TABLE dim_legislator ADD COLUMN district_2026 INTEGER")

    if "dim_bill" in tables:
        cols = _columns(conn, "dim_bill")
        if "plain_language_summary" not in cols:
            conn.execute(
                "ALTER TABLE dim_bill ADD COLUMN plain_language_summary TEXT"
            )
