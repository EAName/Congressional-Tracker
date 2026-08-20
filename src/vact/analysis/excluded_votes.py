"""Excluded roll calls transparency (Prompt 17).

Writes `data/votes_excluded.csv` from the warehouse using pre-registered reason
codes in VOTE_INCLUSION_SPEC.md.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

import duckdb
import yaml

from vact.analysis.scoring import ScoringConfig, load_scoring_config
from vact.paths import DATA_DIR, REPO_ROOT
from vact.warehouse.connection import ensure_schema

EXCLUDED_PATH = DATA_DIR / "votes_excluded.csv"
SYMMETRY_CONFIG = REPO_ROOT / "config" / "symmetry_audit.yaml"

EXCLUDED_COLUMNS = (
    "vote_id",
    "vote_date",
    "vote_category",
    "bill_id",
    "impact_tag",
    "reason_code",
    "sponsor_party",
    "source_url",
    "notes",
)


def _near_unanimous_threshold() -> float:
    if SYMMETRY_CONFIG.is_file():
        payload = yaml.safe_load(SYMMETRY_CONFIG.read_text(encoding="utf-8")) or {}
        return float(payload.get("near_unanimous_share", 0.95))
    return 0.95


def _is_rule_resolution(row: dict[str, Any], config: ScoringConfig) -> bool:
    if not config.exclude_rule_resolutions:
        return False
    bill_type = (row.get("bill_type") or "").lower()
    if bill_type not in config.rule_resolution_bill_types:
        return False
    title = row.get("title") or row.get("short_title") or ""
    pattern = config.rule_resolution_title_pattern
    if not pattern or not title:
        return False
    return re.search(pattern, title) is not None


def _rollcall_unanimous(conn: duckdb.DuckDBPyConnection, vote_id: str, threshold: float) -> bool:
    row = conn.execute(
        """
        SELECT
            sum(CASE WHEN position = 'YEA' THEN 1 ELSE 0 END) AS yea,
            sum(CASE WHEN position = 'NAY' THEN 1 ELSE 0 END) AS nay
        FROM fact_member_vote
        WHERE vote_id = ?
          AND position IN ('YEA', 'NAY')
        """,
        [vote_id],
    ).fetchone()
    if not row:
        return False
    yea, nay = int(row[0] or 0), int(row[1] or 0)
    total = yea + nay
    if total == 0:
        return False
    return max(yea, nay) / total >= threshold


def _exclusion_reason(
    raw: dict[str, Any],
    cfg: ScoringConfig,
    conn: duckdb.DuckDBPyConnection,
    threshold: float,
) -> str | None:
    cat = raw["vote_category"]
    if cat in cfg.exclude_categories:
        return "PROCEDURAL_CATEGORY"
    if cat not in cfg.include_categories:
        return "PROCEDURAL_CATEGORY"
    if _is_rule_resolution(raw, cfg):
        return "RULE_RESOLUTION"
    if not raw["impact_tag"]:
        return "NO_IMPACT_TAG"
    if raw["valence"] not in (-1, 1):
        return "UNADJUDICATED_DIRECTION"
    if raw["valence_source"] != "HUMAN":
        return "UNADJUDICATED_DIRECTION"
    if _rollcall_unanimous(conn, raw["vote_id"], threshold):
        return "NEAR_UNANIMOUS"
    return None


def build_excluded_rows(
    conn: duckdb.DuckDBPyConnection,
    config: ScoringConfig | None = None,
) -> list[dict[str, str]]:
    cfg = config or load_scoring_config()
    threshold = _near_unanimous_threshold()
    rows = conn.execute(
        """
        SELECT
            v.vote_id,
            CAST(v.vote_date AS VARCHAR) AS vote_date,
            v.vote_category,
            coalesce(v.bill_id, '') AS bill_id,
            coalesce(v.source_url, '') AS source_url,
            coalesce(b.bill_type, '') AS bill_type,
            coalesce(b.title, '') AS title,
            coalesce(b.short_title, '') AS short_title,
            coalesce(i.impact_tag, '') AS impact_tag,
            val.valence,
            val.valence_source,
            coalesce(sp.party, '') AS sponsor_party
        FROM fact_vote v
        LEFT JOIN dim_bill b ON b.bill_id = v.bill_id
        LEFT JOIN bridge_vote_impact i ON i.vote_id = v.vote_id
        LEFT JOIN fact_vote_valence val
            ON val.vote_id = v.vote_id AND val.impact_tag = i.impact_tag
        LEFT JOIN dim_legislator sp
            ON sp.bioguide_id = b.sponsor_bioguide
           AND sp.is_incumbent
        ORDER BY v.vote_date, v.vote_id, coalesce(i.impact_tag, '')
        """
    ).fetchall()
    cols = [
        "vote_id",
        "vote_date",
        "vote_category",
        "bill_id",
        "source_url",
        "bill_type",
        "title",
        "short_title",
        "impact_tag",
        "valence",
        "valence_source",
        "sponsor_party",
    ]
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for rec in rows:
        raw = dict(zip(cols, rec, strict=True))
        tag = raw["impact_tag"] or ""
        key = (raw["vote_id"], tag)
        if key in seen:
            continue
        reason = _exclusion_reason(raw, cfg, conn, threshold)
        if reason is None:
            continue
        seen.add(key)
        out.append(
            {
                "vote_id": raw["vote_id"],
                "vote_date": raw["vote_date"][:10],
                "vote_category": raw["vote_category"],
                "bill_id": raw["bill_id"],
                "impact_tag": tag,
                "reason_code": reason,
                "sponsor_party": raw["sponsor_party"],
                "source_url": raw["source_url"],
                "notes": "",
            }
        )
    return out


def write_excluded_csv(rows: list[dict[str, str]], path: Path | None = None) -> Path:
    dest = path or EXCLUDED_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(EXCLUDED_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)
    return dest


def export_excluded_votes(
    conn: duckdb.DuckDBPyConnection,
    *,
    config: ScoringConfig | None = None,
    path: Path | None = None,
) -> Path:
    ensure_schema(conn)
    rows = build_excluded_rows(conn, config)
    return write_excluded_csv(rows, path)


def load_excluded_csv(path: Path | None = None) -> list[dict[str, str]]:
    dest = path or EXCLUDED_PATH
    if not dest.is_file():
        return []
    with dest.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))
