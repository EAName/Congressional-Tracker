"""Apply a filled adjudication worksheet.

The worksheet is the blind surface a person actually works in: bill title, CRS
description, theme. No party columns, no vote counts. This module reads the
filled file back and records the decisions — 119th rows as HUMAN valence in the
warehouse, challenger rows as adjudicated in the historical review queue.

It refuses to guess. A blank `valence` is skipped, not defaulted, and a scored
row (+1/-1) without a `plain_language_summary` is rejected because publication
surfaces require one.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Sequence
from typing import Any

from vact.paths import DATA_DIR

WORKSHEET_PATH = DATA_DIR / "adjudication_worksheet.csv"

# The blind surface. Party, caucus splits and member positions are deliberately
# absent: the spec requires valence to be set without seeing who voted how, and
# the cheapest way to guarantee that is to never put it in the file.
WORKSHEET_COLUMNS = (
    "queue",
    "who",
    "vote_id",
    "date",
    "bill",
    "theme",
    "policy_area",
    "title",
    "crs_lead",
    "valence",
    "plain_language_summary",
    "coded_blind",
    "notes",
)

_PENDING_SQL = """
SELECT DISTINCT
    v.vote_id,
    CAST(v.vote_date AS VARCHAR) AS vote_date,
    coalesce(v.bill_id, '') AS bill_id,
    b.impact_tag,
    coalesce(d.policy_area, '') AS policy_area,
    coalesce(d.title, '') AS title
FROM fact_vote v
JOIN bridge_vote_impact b ON b.vote_id = v.vote_id
LEFT JOIN dim_bill d ON d.bill_id = v.bill_id
LEFT JOIN fact_vote_valence val
       ON val.vote_id = v.vote_id AND val.impact_tag = b.impact_tag
WHERE val.vote_id IS NULL
  AND v.vote_category IN ({category_ph})
  AND (? IS NULL OR v.chamber = ?)
ORDER BY b.impact_tag, v.vote_date, v.vote_id
"""
HISTORICAL_REVIEW_PATH = DATA_DIR / "historical_rollcall_review.csv"
VALID_VALENCE = {"-1", "0", "1", "+1"}


class WorksheetError(ValueError):
    """Worksheet failed validation. Nothing is applied."""


@dataclass
class WorksheetPlan:
    current: list[dict[str, Any]] = field(default_factory=list)
    historical: list[dict[str, Any]] = field(default_factory=list)
    skipped_blank: int = 0
    problems: list[str] = field(default_factory=list)
    missing_summary: list[str] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.current) + len(self.historical)


def load_worksheet(path: Path | None = None) -> list[dict[str, str]]:
    dest = path or WORKSHEET_PATH
    if not dest.is_file():
        raise WorksheetError(f"worksheet not found: {dest}")
    with dest.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def plan_worksheet(path: Path | None = None) -> WorksheetPlan:
    """Validate every filled row before touching anything."""
    plan = WorksheetPlan()
    for i, row in enumerate(load_worksheet(path), start=2):
        raw = (row.get("valence") or "").strip()
        if not raw:
            plan.skipped_blank += 1
            continue
        if raw not in VALID_VALENCE:
            plan.problems.append(f"line {i}: valence {raw!r} must be +1, -1 or 0")
            continue
        valence = int(raw)
        summary = (row.get("plain_language_summary") or "").strip()
        if valence != 0 and not summary:
            # Recorded, but flagged. docs/ and briefs refuse rows without a
            # summary; web/ does not currently enforce that gate, so these will
            # reach the dashboard unsummarised.
            plan.missing_summary.append(row.get("vote_id") or f"line {i}")
        entry = {
            "vote_id": (row.get("vote_id") or "").strip(),
            "impact_tag": (row.get("theme") or "").strip(),
            "valence": valence,
            "plain_language_summary": summary,
            "coded_blind": (row.get("coded_blind") or "true").strip().lower() != "false",
            "notes": (row.get("notes") or "").strip(),
        }
        if not entry["vote_id"] or not entry["impact_tag"]:
            plan.problems.append(f"line {i}: missing vote_id or theme")
            continue
        if (row.get("queue") or "").strip() == "historical":
            plan.historical.append(entry)
        else:
            plan.current.append(entry)
    return plan


def apply_current(conn, entries: list[dict[str, Any]]) -> int:
    """Write 119th decisions as HUMAN valence."""
    from vact.analysis.scoring import set_valence

    for e in entries:
        set_valence(
            conn,
            vote_id=e["vote_id"],
            impact_tag=e["impact_tag"],
            valence=e["valence"],
            source="HUMAN",
        )
    return len(entries)


def apply_historical(entries: list[dict[str, Any]], path: Path | None = None) -> int:
    """Mark challenger rows adjudicated in the historical review queue."""
    dest = path or HISTORICAL_REVIEW_PATH
    if not dest.is_file():
        raise WorksheetError(f"historical review queue not found: {dest}")
    raw = dest.read_bytes()
    crlf = b"\r\n" in raw
    rows = list(csv.DictReader(raw.decode("utf-8").splitlines()))
    if not rows:
        return 0
    by_id = {e["vote_id"]: e for e in entries}
    touched = 0
    for row in rows:
        e = by_id.get(row["vote_id"])
        if e is None:
            continue
        row["adjudicated"] = "true"
        row["suggested_theme"] = e["impact_tag"]
        if e["plain_language_summary"]:
            row["plain_language_summary"] = e["plain_language_summary"]
        if e["notes"]:
            row["notes"] = e["notes"]
        touched += 1
    import io

    sio = io.StringIO()
    w = csv.DictWriter(sio, fieldnames=list(rows[0]), lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    out = sio.getvalue().encode("utf-8")
    if crlf:
        out = out.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    dest.write_bytes(out)
    return touched



def build_worksheet_rows(
    conn,
    *,
    chamber: str | None = None,
    config: Any | None = None,
) -> list[dict[str, str]]:
    """
    Rows for every (vote, theme) pair that clears category and tagging but has no
    valence yet, in the blind worksheet shape.

    `valence` and `plain_language_summary` are left empty on purpose. Pre-filling
    either would be the tool answering the question it is asking, and a title in
    statute-speak is not a plain-language summary.
    """
    from vact.analysis.scoring import load_scoring_config

    cfg = config or load_scoring_config()
    categories = sorted(cfg.include_categories)
    sql = _PENDING_SQL.format(category_ph=", ".join("?" for _ in categories))
    raw = conn.execute(sql, [*categories, chamber, chamber]).fetchall()
    return [
        {
            "queue": "119th",
            "who": "incumbents",
            "vote_id": vote_id,
            "date": vote_date,
            "bill": bill_id,
            "theme": impact_tag,
            "policy_area": policy_area,
            "title": title,
            "crs_lead": "",
            "valence": "",
            "plain_language_summary": "",
            "coded_blind": "true",
            "notes": "",
        }
        for vote_id, vote_date, bill_id, impact_tag, policy_area, title in raw
    ]


def write_worksheet(rows: Sequence[dict[str, str]], path: Path | None = None) -> Path:
    """Write a blind worksheet. Refuses to clobber a file that has filled rows."""
    dest = path or WORKSHEET_PATH
    if dest.is_file():
        existing = load_worksheet(dest)
        filled = [r for r in existing if (r.get("valence") or "").strip()]
        if filled:
            raise WorksheetError(
                f"{dest} already holds {len(filled)} filled row(s); "
                "apply or move it before regenerating"
            )
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(WORKSHEET_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)
    return dest
