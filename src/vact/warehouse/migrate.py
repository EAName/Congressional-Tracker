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

    if "fact_vote" in tables:
        cols = _columns(conn, "fact_vote")
        if "present_total" not in cols:
            conn.execute("ALTER TABLE fact_vote ADD COLUMN present_total INTEGER")
        if "not_voting_total" not in cols:
            conn.execute(
                "ALTER TABLE fact_vote ADD COLUMN not_voting_total INTEGER"
            )
        # Backfill present/NV from member rows when null (Prompt 8 columns).
        conn.execute(
            """
            UPDATE fact_vote v
            SET
                present_total = (
                    SELECT count(*) FROM fact_member_vote m
                    WHERE m.vote_id = v.vote_id AND m.position = 'PRESENT'
                ),
                not_voting_total = (
                    SELECT count(*) FROM fact_member_vote m
                    WHERE m.vote_id = v.vote_id AND m.position = 'NOT_VOTING'
                )
            WHERE v.present_total IS NULL OR v.not_voting_total IS NULL
            """
        )
