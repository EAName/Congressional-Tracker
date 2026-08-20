"""Blind valence review queue (Prompt 17).

Pending `(vote_id, impact_tag)` pairs without party breakdown columns. Operators
commit axis direction here before promoting valence to HUMAN.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Sequence

import duckdb

from vact.paths import DATA_DIR
from vact.warehouse.connection import ensure_schema

QUEUE_PATH = DATA_DIR / "valence_review_queue.csv"

QUEUE_COLUMNS = (
    "vote_id",
    "vote_date",
    "vote_category",
    "bill_id",
    "impact_tag",
    "plain_language_summary",
    "proposed_valence",
    "proposed_source",
    "status",
    "notes",
)


def build_review_queue_rows(conn: duckdb.DuckDBPyConnection) -> list[dict[str, str]]:
    """Rows needing human valence without caucus breakdown fields."""
    raw = conn.execute(
        """
        SELECT DISTINCT
            v.vote_id,
            CAST(v.vote_date AS VARCHAR) AS vote_date,
            v.vote_category,
            coalesce(v.bill_id, '') AS bill_id,
            i.impact_tag,
            coalesce(b.plain_language_summary, '') AS plain_language_summary,
            val.valence,
            coalesce(val.valence_source, '') AS valence_source
        FROM fact_vote v
        JOIN bridge_vote_impact i ON i.vote_id = v.vote_id
        LEFT JOIN dim_bill b ON b.bill_id = v.bill_id
        LEFT JOIN fact_vote_valence val
            ON val.vote_id = v.vote_id AND val.impact_tag = i.impact_tag
        WHERE val.valence IS NULL
           OR val.valence NOT IN (-1, 1)
           OR val.valence_source IS NULL
           OR val.valence_source != 'HUMAN'
        ORDER BY v.vote_date, v.vote_id, i.impact_tag
        """
    ).fetchall()
    cols = [
        "vote_id",
        "vote_date",
        "vote_category",
        "bill_id",
        "impact_tag",
        "plain_language_summary",
        "valence",
        "valence_source",
    ]
    out: list[dict[str, str]] = []
    for rec in raw:
        row = dict(zip(cols, rec, strict=True))
        proposed = row["valence"]
        out.append(
            {
                "vote_id": row["vote_id"],
                "vote_date": row["vote_date"][:10],
                "vote_category": row["vote_category"],
                "bill_id": row["bill_id"],
                "impact_tag": row["impact_tag"],
                "plain_language_summary": row["plain_language_summary"],
                "proposed_valence": "" if proposed is None else str(int(proposed)),
                "proposed_source": row["valence_source"],
                "status": "pending",
                "notes": "",
            }
        )
    return out


def write_review_queue_csv(rows: list[dict[str, str]], path: Path | None = None) -> Path:
    dest = path or QUEUE_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(QUEUE_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)
    return dest


def export_review_queue(
    conn: duckdb.DuckDBPyConnection,
    *,
    path: Path | None = None,
) -> Path:
    ensure_schema(conn)
    rows = build_review_queue_rows(conn)
    return write_review_queue_csv(rows, path)


def load_review_queue_csv(path: Path | None = None) -> list[dict[str, str]]:
    dest = path or QUEUE_PATH
    if not dest.is_file():
        return []
    with dest.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def summarize_review_queue(rows: Sequence[dict[str, str]]) -> dict[str, Any]:
    pending = sum(1 for r in rows if (r.get("status") or "pending") == "pending")
    return {"n_total": len(rows), "n_pending": pending}
