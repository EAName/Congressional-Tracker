"""
Publication eligibility for activist-facing surfaces.

Sheets (audit) may show broader rows; static site and social cards must only
emit publication-eligible votes. Counts are always live queries — never persist
a frozen summary metric (AGENTS.md rule 8).
"""

from __future__ import annotations

from typing import Any

import duckdb

# Live filter: tagged policy votes with human plain-language copy, and no
# unadjudicated LLM tags on the vote.
PUBLICATION_VOTES_SQL = """
SELECT DISTINCT
    v.vote_id,
    v.vote_date,
    v.chamber,
    v.vote_category,
    v.bill_id,
    b.plain_language_summary
FROM fact_vote v
INNER JOIN bridge_vote_impact i ON i.vote_id = v.vote_id
INNER JOIN dim_bill b ON b.bill_id = v.bill_id
WHERE b.plain_language_summary IS NOT NULL
  AND length(trim(b.plain_language_summary)) > 0
  AND NOT EXISTS (
      SELECT 1
      FROM bridge_vote_impact llm
      WHERE llm.vote_id = v.vote_id
        AND llm.classified_by = 'LLM'
  )
"""


def list_publication_votes(conn: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    """Return activist-facing eligible votes via a live warehouse query."""
    rows = conn.execute(PUBLICATION_VOTES_SQL).fetchall()
    cols = [
        "vote_id",
        "vote_date",
        "chamber",
        "vote_category",
        "bill_id",
        "plain_language_summary",
    ]
    return [dict(zip(cols, r)) for r in rows]


def assert_publication_gates(conn: duckdb.DuckDBPyConnection) -> None:
    """
    Publication gate contracts.

    1. Every row returned by the publication query has a non-null summary.
    2. No published vote carries an unadjudicated LLM classification.
    """
    published = list_publication_votes(conn)
    for row in published:
        summary = row["plain_language_summary"]
        if summary is None or not str(summary).strip():
            raise AssertionError(
                f"publication surface includes vote without summary: {row['vote_id']}"
            )

    llm_leaks = conn.execute(
        """
        SELECT DISTINCT p.vote_id
        FROM ({pub}) p
        JOIN bridge_vote_impact i ON i.vote_id = p.vote_id
        WHERE i.classified_by = 'LLM'
        """.format(pub=PUBLICATION_VOTES_SQL)
    ).fetchall()
    if llm_leaks:
        raise AssertionError(
            f"publication surface includes unadjudicated LLM tags: {llm_leaks[:10]}"
        )
