"""Derive vote_category from ref_vote_category_rule (SQL mapping table)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import duckdb

from vact.paths import DATA_DIR, SQL_DIR
from vact.warehouse.connection import apply_sql_file, connect

RECATEGORIZE_DIFF_PATH = DATA_DIR / "reports" / "recategorize_diff.md"


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


def recategorize_all(
    *,
    confirm: bool,
    warehouse_path: Path | None = None,
) -> Path:
    """
    Re-derive `fact_vote.vote_category` from the current rule table.

    `vote_category` is assigned in `warehouse/load.py` when a roll call is first
    loaded and never revisited, so editing `seed_vote_category_rules.sql` leaves
    every existing row on the category it got under the old rulebook. Without
    this the rulebook is only versioned going forward, which makes a rule fix
    silently retroactive-in-name-only.

    Writes a diff before applying, like `classify.reclassify_all`.
    """
    if not confirm:
        raise RuntimeError("refusing to recategorize without --confirm")

    conn = connect(warehouse_path)
    try:
        ensure_category_rules(conn)
        sql = (SQL_DIR / "recategorize_votes.sql").read_text(encoding="utf-8")
        rows = conn.execute(sql).fetchall()

        unmatched = [r for r in rows if r[4] is None]
        if unmatched:
            raise RuntimeError(
                f"{len(unmatched)} votes matched no category rule; "
                "the rule-8 fallback should make this impossible"
            )
        changed = [r for r in rows if r[3] != r[4]]

        moves: dict[tuple[str, str, str], int] = {}
        for _vid, chamber, _q, old, new in changed:
            moves[(chamber, old, new)] = moves.get((chamber, old, new), 0) + 1

        RECATEGORIZE_DIFF_PATH.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# Recategorize diff",
            "",
            f"Generated at {datetime.now(UTC).isoformat()}",
            "",
            f"- votes examined: {len(rows)}",
            f"- categories changed: {len(changed)}",
            "",
            "## Moves",
            "",
            "| chamber | from | to | n |",
            "|---------|------|----|---|",
        ]
        for (chamber, old, new), n in sorted(moves.items(), key=lambda kv: -kv[1]):
            lines.append(f"| {chamber} | {old} | {new} | {n} |")
        lines += ["", "## Changed votes", ""]
        for vid, chamber, question, old, new in changed:
            lines.append(f"- `{vid}` ({chamber}) {old} -> {new}: {question}")
        RECATEGORIZE_DIFF_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

        if changed:
            conn.execute("CREATE OR REPLACE TEMP TABLE _recat (vote_id VARCHAR, cat VARCHAR)")
            conn.executemany(
                "INSERT INTO _recat VALUES (?, ?)", [(r[0], r[4]) for r in changed]
            )
            conn.execute(
                "UPDATE fact_vote SET vote_category = ("
                "  SELECT cat FROM _recat WHERE _recat.vote_id = fact_vote.vote_id"
                ") WHERE vote_id IN (SELECT vote_id FROM _recat)"
            )
        return RECATEGORIZE_DIFF_PATH
    finally:
        conn.close()
