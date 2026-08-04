"""Opaque warehouse metadata (SHAs, watermarks). Never store summary metrics here."""

from __future__ import annotations

from datetime import UTC, datetime

import duckdb

from vact.warehouse.connection import connect, ensure_schema

META_LEGISLATORS_SHA = "congress_legislators.main_sha"
META_DELEGATION_FP = "va_delegation.fingerprint"


def get_meta(conn: duckdb.DuckDBPyConnection, key: str) -> str | None:
    row = conn.execute(
        "SELECT meta_value FROM warehouse_meta WHERE meta_key = ?",
        [key],
    ).fetchone()
    return None if row is None else str(row[0])


def set_meta(conn: duckdb.DuckDBPyConnection, key: str, value: str) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    conn.execute(
        """
        INSERT INTO warehouse_meta AS t (meta_key, meta_value, updated_at_utc)
        VALUES (?, ?, ?)
        ON CONFLICT (meta_key) DO UPDATE SET
            meta_value = excluded.meta_value,
            updated_at_utc = excluded.updated_at_utc
        """,
        [key, value, now],
    )


def warehouse_content_fingerprint(conn: duckdb.DuckDBPyConnection) -> str:
    """
    Coarse content fingerprint for silent no-op detection.

    Not a published metric — used only to decide whether an incremental run
    changed warehouse content.
    """
    row = conn.execute(
        """
        SELECT
            (SELECT count(*) FROM fact_vote),
            (SELECT count(*) FROM fact_member_vote),
            (SELECT count(*) FROM bridge_vote_impact),
            (SELECT coalesce(string_agg(vote_id, ',' ORDER BY vote_id), '')
             FROM (SELECT vote_id FROM fact_vote ORDER BY vote_id DESC LIMIT 25))
        """
    ).fetchone()
    return "|".join("" if x is None else str(x) for x in row)
