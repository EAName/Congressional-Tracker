"""Derive vote_category from ref_vote_category_rule (SQL mapping table)."""

from __future__ import annotations

from pathlib import Path

import duckdb

from vact.paths import SQL_DIR
from vact.warehouse.connection import apply_sql_file, connect


def ensure_category_rules(conn: duckdb.DuckDBPyConnection) -> None:
    apply_sql_file(conn, "schema.sql")
    apply_sql_file(conn, "seed_vote_category_rules.sql")


def classify_vote_category(
    vote_question: str | None,
    vote_type: str | None,
    *,
    conn: duckdb.DuckDBPyConnection | None = None,
    warehouse_path: Path | None = None,
) -> str:
    """
    Return the winning vote_category from ref_vote_category_rule.

    Classification is done entirely in SQL against the seeded rule table.
    """
    owns = conn is None
    db = conn or connect(warehouse_path)
    try:
        ensure_category_rules(db)
        sql = (SQL_DIR / "classify_vote_category.sql").read_text(encoding="utf-8")
        row = db.execute(sql, [vote_question or "", vote_type or ""]).fetchone()
        if row is None or row[0] is None:
            raise RuntimeError(
                f"no vote_category rule matched question={vote_question!r} type={vote_type!r}"
            )
        return str(row[0])
    finally:
        if owns:
            db.close()
