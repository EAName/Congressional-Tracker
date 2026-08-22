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
SUMMARY_ROOT = DATA_DIR / "raw" / "congress_summaries"

QUEUE_COLUMNS = (
    "vote_id",
    "vote_date",
    "vote_category",
    "bill_id",
    "impact_tag",
    "plain_language_summary",
    "crs_lead",
    "proposed_valence",
    "proposed_source",
    "status",
    "notes",
)


def build_review_queue_rows(
    conn: duckdb.DuckDBPyConnection,
    *,
    config: "ScoringConfig | None" = None,
) -> list[dict[str, str]]:
    """Rows needing human valence, without caucus breakdown fields.

    Restricted to scoreable vote categories. Without that filter the queue asked
    for adjudication on PROCEDURAL, MOTION_TO_RECOMMIT and SUSPENSION votes,
    which `scoreable` excludes by category no matter what valence they carry —
    143 rows emitted where only 39 could ever affect a score.
    """
    from vact.analysis.scoring import load_scoring_config

    cfg = config or load_scoring_config()
    include = sorted(cfg.include_categories)
    ph = ", ".join("?" for _ in include)
    raw = conn.execute(
        f"""
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
        WHERE v.vote_category IN ({ph})
          AND (
                val.valence IS NULL
             OR val.valence NOT IN (-1, 1)
             OR val.valence_source IS NULL
             OR val.valence_source != 'HUMAN'
          )
        ORDER BY v.vote_date, v.vote_id, i.impact_tag
        """,
        include,
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


_BOILERPLATE = __import__("re").compile(
    r"^\(This measure has not been amended[^)]*\)\s*"
)
_TAG = __import__("re").compile(r"<[^>]+>")
_WS = __import__("re").compile(r"\s+")


def attach_crs_lead(
    rows: Sequence[dict[str, str]], *, chars: int = 420, root: Path | None = None
) -> list[dict[str, str]]:
    """Add the opening of each bill's CRS summary as reading material.

    Reference text only — never matched against. Full summaries proved useless
    for rule matching (Dodd-Frank's 208k-character summary contains 'exempt', so
    a keyword rule proposed it as regulatory *relief*). What they are good for is
    telling a human what a bill does without opening a browser.
    """
    import json

    base = root or SUMMARY_ROOT
    cache: dict[str, str] = {}
    out = []
    for row in rows:
        bill = (row.get("bill_id") or "").strip()
        lead = ""
        if bill:
            if bill not in cache:
                parts = bill.split("-")
                text = ""
                if len(parts) == 3:
                    path = base / parts[2] / f"{parts[0]}{parts[1]}.json"
                    if path.is_file():
                        try:
                            items = json.loads(path.read_text(encoding="utf-8")).get(
                                "summaries"
                            ) or []
                            items.sort(key=lambda r: (r.get("actionDate") or ""))
                            if items:
                                text = _WS.sub(
                                    " ",
                                    _TAG.sub(" ", items[-1].get("text", "")).replace(
                                        "&nbsp;", " "
                                    ),
                                ).strip()
                                text = _BOILERPLATE.sub("", text)
                        except Exception:
                            text = ""
                cache[bill] = text
            lead = cache[bill][:chars]
        out.append({**row, "crs_lead": lead})
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
    config: "ScoringConfig | None" = None,
) -> Path:
    ensure_schema(conn)
    rows = build_review_queue_rows(conn, config=config)
    return write_review_queue_csv(attach_crs_lead(rows), path)


def load_review_queue_csv(path: Path | None = None) -> list[dict[str, str]]:
    dest = path or QUEUE_PATH
    if not dest.is_file():
        return []
    with dest.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def summarize_review_queue(rows: Sequence[dict[str, str]]) -> dict[str, Any]:
    pending = sum(1 for r in rows if (r.get("status") or "pending") == "pending")
    return {"n_total": len(rows), "n_pending": pending}
