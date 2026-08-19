"""Versioned adjudication layer: `data/votes.csv`.

This file is the operator-facing source of truth for scoring after Prompt 1.
DuckDB remains the ingest warehouse. Sheets remains a read-only audit export.

Unique key is `(member_bioguide_id, rollcall_id, theme)` — valence is per
`(vote_id, impact_tag)`, so a roll call with two scoreable tags is two rows.
The kit's `(member, rollcall)` uniqueness would drop multi-tag votes.

Theme values are warehouse impact tags (`FEDERAL_CONTRACTING`, …), not a
two-value enum. `axis_direction` is the only political judgment on the row
(`advance` = valence +1, `oppose` = valence −1).

Signed scores are never stored here (AGENTS.md §8). Downstream estimators
read this file and recompute live.
"""

from __future__ import annotations

import csv
import subprocess
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Sequence

import duckdb
import structlog
from pydantic import BaseModel, ConfigDict, field_validator

from vact.analysis.scoring import (
    ScoringConfig,
    _rule_resolution_exclusion,
    load_scoring_config,
)
from vact.paths import REPO_ROOT
from vact.transforms.districts import require_map_version
from vact.warehouse.connection import connect, ensure_schema

logger = structlog.get_logger(__name__)

VOTES_CSV_PATH = REPO_ROOT / "data" / "votes.csv"
DIFF_REPORT_PATH = REPO_ROOT / "data" / "reports" / "votes_diff.md"
SHEETS_DIFF_PATH = REPO_ROOT / "data" / "reports" / "votes_sheets_diff.md"

CSV_COLUMNS: tuple[str, ...] = (
    "member_bioguide_id",
    "member_name",
    "district",
    "party",
    "congress",
    "chamber",
    "rollcall_id",
    "rollcall_date",
    "bill_id",
    "theme",
    "axis_direction",
    "vote_cast",
    "contested",
    "adjudication_note",
    "adjudicator",
    "adjudication_date",
    "source_url",
    "plain_language_summary",
)

VOTE_CAST_VALUES = frozenset({"yea", "nay", "present", "not_voting"})
AXIS_VALUES = frozenset({"advance", "oppose"})
CHAMBER_VALUES = frozenset({"House", "Senate"})
ADJUDICATOR_VALUES = frozenset({"RULE", "LLM", "HUMAN"})


class AxisDirection(StrEnum):
    ADVANCE = "advance"
    OPPOSE = "oppose"


class VoteCast(StrEnum):
    YEA = "yea"
    NAY = "nay"
    PRESENT = "present"
    NOT_VOTING = "not_voting"


class VotesValidationError(ValueError):
    """CSV failed structural / business-rule validation. Fail loud."""


class VoteRow(BaseModel):
    """One adjudicated member × roll call × theme observation."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    member_bioguide_id: str
    member_name: str
    district: str = ""
    party: str = ""
    congress: int
    chamber: str
    rollcall_id: str
    rollcall_date: str
    bill_id: str = ""
    theme: str
    axis_direction: AxisDirection
    vote_cast: VoteCast
    contested: bool
    adjudication_note: str = ""
    adjudicator: str
    adjudication_date: str = ""
    source_url: str
    plain_language_summary: str = ""

    @field_validator(
        "member_bioguide_id",
        "member_name",
        "rollcall_id",
        "theme",
        "source_url",
        mode="before",
    )
    @classmethod
    def _strip_required(cls, value: Any) -> str:
        text = "" if value is None else str(value).strip()
        if not text:
            raise ValueError("required field is empty")
        return text

    @field_validator(
        "district",
        "party",
        "bill_id",
        "adjudication_note",
        "adjudication_date",
        "plain_language_summary",
        mode="before",
    )
    @classmethod
    def _strip_optional(cls, value: Any) -> str:
        return "" if value is None else str(value).strip()

    @field_validator("chamber", mode="before")
    @classmethod
    def _chamber(cls, value: Any) -> str:
        text = "" if value is None else str(value).strip()
        if text not in CHAMBER_VALUES:
            raise ValueError(f"chamber must be House or Senate, got {text!r}")
        return text

    @field_validator("adjudicator", mode="before")
    @classmethod
    def _adjudicator(cls, value: Any) -> str:
        text = "" if value is None else str(value).strip()
        if text not in ADJUDICATOR_VALUES:
            raise ValueError(f"adjudicator must be RULE|LLM|HUMAN, got {text!r}")
        return text

    @field_validator("contested", mode="before")
    @classmethod
    def _contested(cls, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in {"true", "1", "yes"}:
            return True
        if text in {"false", "0", "no", ""}:
            return False
        raise ValueError(f"contested must be boolean, got {value!r}")

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.member_bioguide_id, self.rollcall_id, self.theme)

    @property
    def valence(self) -> int:
        return 1 if self.axis_direction is AxisDirection.ADVANCE else -1

    @property
    def position_upper(self) -> str:
        return self.vote_cast.value.upper()

    @property
    def district_number(self) -> int | None:
        if not self.district:
            return None
        try:
            return int(self.district)
        except ValueError:
            return None


_EXTRACT_SQL = """
WITH active AS (
    SELECT *
    FROM dim_legislator
    WHERE is_incumbent
       OR (term_start <= current_date AND current_date < term_end)
),
members AS (
    SELECT
        a.bioguide_id,
        a.full_name,
        a.chamber,
        a.party,
        a.{district_col} AS district_number
    FROM (
        SELECT
            a.*,
            row_number() OVER (
                PARTITION BY a.bioguide_id ORDER BY a.term_start DESC
            ) AS rn
        FROM active a
    ) a
    WHERE a.rn = 1
),
scoreable AS (
    SELECT
        v.vote_id,
        v.congress,
        v.chamber AS roll_chamber,
        CAST(v.vote_date AS VARCHAR) AS vote_date,
        coalesce(v.bill_id, '') AS bill_id,
        coalesce(v.source_url, '') AS source_url,
        coalesce(b.plain_language_summary, '') AS plain_language_summary,
        val.impact_tag,
        val.valence,
        val.valence_source,
        CAST(val.adjudicated_at_utc AS VARCHAR) AS adjudicated_at_utc
    FROM fact_vote_valence val
    JOIN fact_vote v ON v.vote_id = val.vote_id
    LEFT JOIN dim_bill b ON b.bill_id = v.bill_id
    WHERE val.valence IN (-1, 1)
      AND v.vote_category IN ({category_ph})
      {rule_clause}
)
SELECT
    m.bioguide_id,
    m.full_name,
    CASE WHEN m.district_number IS NULL THEN '' ELSE CAST(m.district_number AS VARCHAR) END,
    coalesce(m.party, ''),
    s.congress,
    m.chamber,
    s.vote_id,
    s.vote_date,
    s.bill_id,
    s.impact_tag,
    CASE WHEN s.valence = 1 THEN 'advance' ELSE 'oppose' END,
    lower(mv.position),
    mv.position IN ('YEA', 'NAY'),
    '',
    s.valence_source,
    substr(coalesce(s.adjudicated_at_utc, ''), 1, 10),
    s.source_url,
    s.plain_language_summary
FROM members m
JOIN scoreable s ON TRUE
JOIN fact_member_vote mv
     ON mv.vote_id = s.vote_id
    AND mv.bioguide_id = m.bioguide_id
WHERE mv.position IN ('YEA', 'NAY', 'PRESENT', 'NOT_VOTING')
ORDER BY s.impact_tag, s.vote_date, s.vote_id, m.bioguide_id
"""


def vote_rows_from_warehouse(
    conn: duckdb.DuckDBPyConnection,
    config: ScoringConfig | None = None,
    *,
    map_version: str = "2021",
) -> list[VoteRow]:
    """Project the scoreable warehouse join into VoteRow records.

    Membership matches `build_scores_frame`: VA incumbents in dim_legislator,
    scoreable categories, adjudicated valence ±1, rule-resolution exclusion.
    """
    require_map_version(map_version)
    cfg = config or load_scoring_config()
    district_col = "district_2025" if map_version == "2021" else "district_2026"
    category_ph = ", ".join("?" for _ in sorted(cfg.include_categories))
    rule_clause, rule_params = _rule_resolution_exclusion(cfg)
    sql = _EXTRACT_SQL.format(
        district_col=district_col, category_ph=category_ph, rule_clause=rule_clause
    )
    raw = conn.execute(sql, [*sorted(cfg.include_categories), *rule_params]).fetchall()
    rows: list[VoteRow] = []
    for rec in raw:
        payload = {col: rec[i] for i, col in enumerate(CSV_COLUMNS)}
        rows.append(VoteRow.model_validate(payload))
    return rows


def load_votes_csv(path: Path | None = None) -> list[VoteRow]:
    dest = path or VOTES_CSV_PATH
    if not dest.is_file():
        raise FileNotFoundError(f"votes.csv not found: {dest}")
    with dest.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in CSV_COLUMNS if c != "plain_language_summary" and c not in (reader.fieldnames or [])]
        if missing:
            raise VotesValidationError(f"votes.csv missing columns: {missing}")
        return [VoteRow.model_validate(rec) for rec in reader]


def write_votes_csv(rows: Sequence[VoteRow], path: Path | None = None) -> Path:
    dest = path or VOTES_CSV_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(
        rows,
        key=lambda r: (r.theme, r.rollcall_date, r.rollcall_id, r.member_bioguide_id),
    )
    with dest.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(CSV_COLUMNS), lineterminator="\n")
        writer.writeheader()
        for row in ordered:
            payload = row.model_dump()
            payload["axis_direction"] = row.axis_direction.value
            payload["vote_cast"] = row.vote_cast.value
            payload["contested"] = "true" if row.contested else "false"
            writer.writerow({col: payload.get(col, "") for col in CSV_COLUMNS})
    return dest


def validate_vote_rows(rows: Sequence[VoteRow]) -> list[str]:
    """Return error strings. Empty means the table is well-formed."""
    errors: list[str] = []
    seen: dict[tuple[str, str, str], int] = {}
    party_by_member: dict[str, str] = {}

    for i, row in enumerate(rows, start=2):  # header = line 1
        loc = f"line {i} {row.key}"
        if row.vote_cast.value not in VOTE_CAST_VALUES:
            errors.append(f"{loc}: vote_cast {row.vote_cast!r} not in {sorted(VOTE_CAST_VALUES)}")
        if row.axis_direction.value not in AXIS_VALUES:
            errors.append(f"{loc}: axis_direction required (advance|oppose)")
        if not row.source_url:
            errors.append(f"{loc}: source_url is required")
        expected_contested = row.vote_cast in {VoteCast.YEA, VoteCast.NAY}
        if row.contested != expected_contested:
            errors.append(
                f"{loc}: contested={row.contested} inconsistent with vote_cast={row.vote_cast.value}"
            )
        if not _is_iso_date(row.rollcall_date):
            errors.append(f"{loc}: rollcall_date must be ISO date, got {row.rollcall_date!r}")
        if row.adjudication_date and not _is_iso_date(row.adjudication_date):
            errors.append(
                f"{loc}: adjudication_date must be ISO date, got {row.adjudication_date!r}"
            )
        if row.key in seen:
            errors.append(f"{loc}: duplicate key {row.key} (also line {seen[row.key]})")
        else:
            seen[row.key] = i
        if row.party:
            prior = party_by_member.get(row.member_bioguide_id)
            if prior is None:
                party_by_member[row.member_bioguide_id] = row.party
            elif prior != row.party:
                errors.append(
                    f"{loc}: party {row.party!r} disagrees with {prior!r} "
                    f"for {row.member_bioguide_id}"
                )
    return errors


def validate_votes_csv(path: Path | None = None) -> list[VoteRow]:
    rows = load_votes_csv(path)
    errors = validate_vote_rows(rows)
    if errors:
        preview = "\n".join(errors[:20])
        extra = f"\n… {len(errors) - 20} more" if len(errors) > 20 else ""
        raise VotesValidationError(f"votes.csv failed validation:\n{preview}{extra}")
    return rows


def _is_iso_date(value: str) -> bool:
    try:
        date.fromisoformat(value[:10])
    except ValueError:
        return False
    return True


def diff_vote_rows(
    previous: Sequence[VoteRow],
    current: Sequence[VoteRow],
) -> dict[str, Any]:
    prev_map = {r.key: r for r in previous}
    curr_map = {r.key: r for r in current}
    added = sorted(curr_map.keys() - prev_map.keys())
    removed = sorted(prev_map.keys() - curr_map.keys())
    changed: list[tuple[str, str, str]] = []
    compare_fields = (
        "axis_direction",
        "vote_cast",
        "contested",
        "adjudicator",
        "adjudication_note",
        "source_url",
        "theme",
        "party",
    )
    for key in sorted(curr_map.keys() & prev_map.keys()):
        a, b = prev_map[key], curr_map[key]
        if any(getattr(a, f) != getattr(b, f) for f in compare_fields):
            changed.append(key)
    return {
        "added": added,
        "removed": removed,
        "changed": changed,
        "n_previous": len(previous),
        "n_current": len(current),
    }


def render_votes_diff_md(diff: dict[str, Any], *, title: str = "votes.csv diff") -> str:
    generated = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    lines = [
        f"# {title}",
        "",
        f"Generated `{generated}`.",
        "",
        f"- previous rows: {diff['n_previous']}",
        f"- current rows: {diff['n_current']}",
        f"- added keys: {len(diff['added'])}",
        f"- removed keys: {len(diff['removed'])}",
        f"- changed keys: {len(diff['changed'])}",
        "",
        "Key = `(member_bioguide_id, rollcall_id, theme)`.",
        "",
    ]
    for label, keys in (
        ("Added", diff["added"]),
        ("Removed", diff["removed"]),
        ("Changed", diff["changed"]),
    ):
        lines.append(f"## {label}")
        lines.append("")
        if not keys:
            lines.append("_none_")
            lines.append("")
            continue
        for key in keys[:200]:
            lines.append(f"- `{key[0]}` · `{key[1]}` · `{key[2]}`")
        if len(keys) > 200:
            lines.append(f"- … {len(keys) - 200} more")
        lines.append("")
    return "\n".join(lines)


def load_committed_votes_csv() -> list[VoteRow] | None:
    """HEAD version of data/votes.csv, or None if untracked / missing."""
    try:
        proc = subprocess.run(
            ["git", "show", "HEAD:data/votes.csv"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    reader = csv.DictReader(proc.stdout.splitlines())
    try:
        return [VoteRow.model_validate(rec) for rec in reader]
    except Exception:
        logger.warning("votes.committed_csv_unreadable")
        return None


def export_votes_csv(
    *,
    map_version: str = "2021",
    warehouse_path: Path | None = None,
    config_path: Path | None = None,
    out_path: Path | None = None,
    previous: Sequence[VoteRow] | None = None,
    diff_path: Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Warehouse → validated CSV + markdown diff vs previous/HEAD."""
    dest = out_path or VOTES_CSV_PATH
    conn = connect(warehouse_path)
    try:
        ensure_schema(conn)
        cfg = load_scoring_config(config_path)
        rows = vote_rows_from_warehouse(conn, cfg, map_version=map_version)
    finally:
        conn.close()

    errors = validate_vote_rows(rows)
    if errors:
        raise VotesValidationError("warehouse extract failed validation:\n" + "\n".join(errors[:20]))

    prior: Sequence[VoteRow]
    if previous is not None:
        prior = previous
    elif dest.is_file():
        prior = load_votes_csv(dest)
    else:
        prior = load_committed_votes_csv() or []

    write_votes_csv(rows, dest)
    diff = diff_vote_rows(prior, rows)
    report = render_votes_diff_md(diff)
    report_dest = diff_path or DIFF_REPORT_PATH
    report_dest.parent.mkdir(parents=True, exist_ok=True)
    report_dest.write_text(report, encoding="utf-8")
    logger.info(
        "votes.export",
        path=str(dest),
        n=len(rows),
        added=len(diff["added"]),
        removed=len(diff["removed"]),
        changed=len(diff["changed"]),
    )
    return dest, diff


def reconcile_sheets_vote_detail(rows: Sequence[VoteRow]) -> dict[str, Any]:
    """Read-only coverage diff vs Sheets Vote Detail. Never writes axis_direction.

    Match is (member_name, rollcall_date, bill_id, vote_cast). Vote Detail has no
    bioguide_id or vote_id, so this is a coverage check, not a join-key audit.
    Missing Sheets creds → skipped.
    """
    from vact.exports.sheets import SheetsConfigError, TAB_DETAIL, _open_client, spreadsheet_id

    try:
        client, _email = _open_client(interactive=False)
        sh = client.open_by_key(spreadsheet_id())
        ws = sh.worksheet(TAB_DETAIL)
        values = ws.get_all_values()
    except SheetsConfigError as err:
        return {"skipped": True, "reason": str(err)}
    except Exception as err:  # noqa: BLE001 — recon is best-effort
        return {"skipped": True, "reason": str(err)}

    if not values:
        return {"skipped": True, "reason": "Vote Detail is empty"}

    header = [h.strip() for h in values[0]]

    def _col(*names: str) -> int | None:
        lower = [h.lower() for h in header]
        for name in names:
            if name.lower() in lower:
                return lower.index(name.lower())
        return None

    i_name = _col("Member", "full_name", "Name")
    i_date = _col("Date", "vote_date")
    i_bill = _col("Bill", "bill_id")
    i_pos = _col("Position", "vote_cast")
    if i_name is None or i_date is None or i_pos is None:
        return {"skipped": True, "reason": f"Vote Detail header not recognized: {header[:8]}"}

    def _sheet_key(rec: list[str]) -> tuple[str, str, str, str]:
        bill = rec[i_bill].strip() if i_bill is not None and i_bill < len(rec) else ""
        pos = rec[i_pos].strip().lower().replace(" ", "_") if i_pos < len(rec) else ""
        return (rec[i_name].strip(), rec[i_date].strip()[:10], bill, pos)

    sheet_keys = {_sheet_key(r) for r in values[1:] if r and any(c.strip() for c in r)}
    csv_keys = {
        (r.member_name, r.rollcall_date, r.bill_id, r.vote_cast.value) for r in rows
    }
    only_csv = sorted(csv_keys - sheet_keys)
    only_sheet = sorted(sheet_keys - csv_keys)
    return {
        "skipped": False,
        "n_csv": len(csv_keys),
        "n_sheet": len(sheet_keys),
        "only_csv": only_csv,
        "only_sheet": only_sheet,
    }


def render_sheets_diff_md(recon: dict[str, Any]) -> str:
    if recon.get("skipped"):
        return (
            "# votes.csv vs Sheets Vote Detail\n\n"
            f"_Skipped:_ {recon.get('reason')}\n"
        )
    lines = [
        "# votes.csv vs Sheets Vote Detail",
        "",
        "Read-only coverage check. Sheets is not the writer of `axis_direction`.",
        "Match key: `(member_name, date, bill_id, vote_cast)` — no bioguide join.",
        "",
        f"- CSV keys: {recon['n_csv']}",
        f"- Sheet keys: {recon['n_sheet']}",
        f"- in CSV not in sheet: {len(recon['only_csv'])}",
        f"- in sheet not in CSV: {len(recon['only_sheet'])}",
        "",
        "## In CSV, not in Vote Detail",
        "",
    ]
    for key in recon["only_csv"][:100]:
        lines.append(f"- {key[0]} · {key[1]} · {key[2]} · {key[3]}")
    if len(recon["only_csv"]) > 100:
        lines.append(f"- … {len(recon['only_csv']) - 100} more")
    if not recon["only_csv"]:
        lines.append("_none_")
    lines += ["", "## In Vote Detail, not in CSV", ""]
    for key in recon["only_sheet"][:100]:
        lines.append(f"- {key[0]} · {key[1]} · {key[2]} · {key[3]}")
    if len(recon["only_sheet"]) > 100:
        lines.append(f"- … {len(recon['only_sheet']) - 100} more")
    if not recon["only_sheet"]:
        lines.append("_none_")
    lines.append("")
    return "\n".join(lines)


def sync_votes(
    *,
    map_version: str = "2021",
    warehouse_path: Path | None = None,
    out_path: Path | None = None,
    sheets: bool = False,
) -> dict[str, Any]:
    """Export from warehouse, validate, optional Sheets coverage diff."""
    dest, diff = export_votes_csv(
        map_version=map_version,
        warehouse_path=warehouse_path,
        out_path=out_path,
    )
    rows = validate_votes_csv(dest)
    result: dict[str, Any] = {"path": dest, "n": len(rows), "diff": diff, "sheets": None}
    if sheets:
        recon = reconcile_sheets_vote_detail(rows)
        SHEETS_DIFF_PATH.parent.mkdir(parents=True, exist_ok=True)
        SHEETS_DIFF_PATH.write_text(render_sheets_diff_md(recon), encoding="utf-8")
        result["sheets"] = recon
    return result


def resolve_votes_path(explicit: Path | None = None) -> Path | None:
    """Return the CSV to score from, or None to keep the DuckDB path."""
    if explicit is not None:
        return explicit
    return VOTES_CSV_PATH if VOTES_CSV_PATH.is_file() else None
