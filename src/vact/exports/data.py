"""Live warehouse queries for Sheets audit and activist-facing publication."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import duckdb

from vact.transforms.districts import TARGET_DISTRICTS_2026, require_map_version

# District / social surfaces. Audit Sheets may show a broader category set.
SITE_SUPPRESSED_CATEGORIES = frozenset(
    {
        "PROCEDURAL",
        "CLOTURE",
        "NOMINATION",
        "SUSPENSION",
        "MOTION_TO_RECOMMIT",
    }
)

SCORECARD_TAGS = (
    "TAX_BURDEN",
    "HEALTH_COSTS",
    "ACCESS_TO_CAPITAL",
    "INPUT_COSTS",
)

# Tags shown on district pages (broader than the four scorecard columns).
DISTRICT_PAGE_MAX_VOTES = 5

ALL_IMPACT_TAGS = (
    "ACCESS_TO_CAPITAL",
    "TAX_BURDEN",
    "FEDERAL_CONTRACTING",
    "HEALTH_COSTS",
    "INPUT_COSTS",
    "REGULATORY_BURDEN",
    "WORKFORCE",
)


def generated_at_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def corpus_vote_count(conn: duckdb.DuckDBPyConnection) -> int:
    row = conn.execute("SELECT count(*) FROM fact_vote").fetchone()
    return int(row[0]) if row else 0


def vote_category_mix(conn: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    """Live counts of fact_vote.vote_category (corpus composition chart)."""
    rows = conn.execute(
        """
        SELECT vote_category, count(*) AS n
        FROM fact_vote
        GROUP BY 1
        ORDER BY n DESC, vote_category
        """
    ).fetchall()
    return [{"label": r[0], "count": int(r[1])} for r in rows]


def impact_tag_mix(conn: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    """Live counts of RULE/HUMAN impact tags (excludes naked LLM)."""
    rows = conn.execute(
        """
        SELECT impact_tag, count(*) AS n
        FROM bridge_vote_impact
        WHERE classified_by IN ('RULE', 'HUMAN')
        GROUP BY 1
        ORDER BY n DESC, impact_tag
        """
    ).fetchall()
    return [{"label": r[0], "count": int(r[1])} for r in rows]


def tagged_vote_count(conn: duckdb.DuckDBPyConnection) -> int:
    row = conn.execute(
        """
        SELECT count(DISTINCT vote_id)
        FROM bridge_vote_impact
        WHERE classified_by IN ('RULE', 'HUMAN')
        """
    ).fetchone()
    return int(row[0]) if row else 0


def publication_ready_count(conn: duckdb.DuckDBPyConnection) -> int:
    """Tagged, non-suppressed votes with a human plain_language_summary."""
    suppressed = sorted(SITE_SUPPRESSED_CATEGORIES)
    ph = ", ".join("?" for _ in suppressed)
    row = conn.execute(
        f"""
        SELECT count(DISTINCT v.vote_id)
        FROM fact_vote v
        JOIN bridge_vote_impact i ON i.vote_id = v.vote_id
        JOIN dim_bill b ON b.bill_id = v.bill_id
        WHERE i.classified_by IN ('RULE', 'HUMAN')
          AND v.vote_category NOT IN ({ph})
          AND b.plain_language_summary IS NOT NULL
          AND length(trim(b.plain_language_summary)) > 0
          AND NOT EXISTS (
              SELECT 1 FROM bridge_vote_impact llm
              WHERE llm.vote_id = v.vote_id AND llm.classified_by = 'LLM'
          )
        """,
        suppressed,
    ).fetchone()
    return int(row[0]) if row else 0


def heatmap_cell(yea: int, nay: int) -> dict[str, Any]:
    """Encode a scorecard cell for CSS heatmap rendering (live counts only)."""
    total = yea + nay
    if total == 0:
        return {
            "label": "—",
            "yea": 0,
            "nay": 0,
            "tone": "empty",
            "pct_yea": None,
        }
    pct = yea / total
    if pct >= 0.7:
        tone = "yea-heavy"
    elif pct <= 0.3:
        tone = "nay-heavy"
    else:
        tone = "split"
    return {
        "label": f"{yea}Y/{nay}N",
        "yea": yea,
        "nay": nay,
        "tone": tone,
        "pct_yea": round(pct, 3),
    }


def heatmap_rows(
    score_rows: list[dict[str, Any]],
    *,
    tags: tuple[str, ...] = SCORECARD_TAGS,
) -> list[dict[str, Any]]:
    out = []
    for row in score_rows:
        cells = {
            tag: heatmap_cell(int(row.get(f"{tag}_yea") or 0), int(row.get(f"{tag}_nay") or 0))
            for tag in tags
        }
        out.append({**row, "cells": cells})
    return out


def list_delegation(
    conn: duckdb.DuckDBPyConnection,
    *,
    map_version: str = "2026",
    as_of: str | None = None,
) -> list[dict[str, Any]]:
    """
    Current VA delegation (13 seats: 11 House + 2 Senate).

    map_version selects which district_YYYY column and dim_district lean to join.
    """
    require_map_version(map_version)
    district_col = "district_2025" if map_version == "2021" else "district_2026"
    rows = conn.execute(
        f"""
        WITH active AS (
            SELECT *
            FROM dim_legislator
            WHERE is_incumbent
               OR (
                    term_start <= current_date
                AND current_date < term_end
               )
        ),
        ranked AS (
            SELECT
                a.*,
                row_number() OVER (
                    PARTITION BY a.bioguide_id
                    ORDER BY a.term_start DESC
                ) AS rn
            FROM active a
        )
        SELECT
            r.bioguide_id,
            r.full_name,
            r.chamber,
            r.party,
            r.{district_col} AS district_number,
            d.partisan_lean,
            coalesce(d.is_target, FALSE) AS is_target,
            r.website
        FROM ranked r
        LEFT JOIN dim_district d
          ON d.district_number = r.{district_col}
         AND d.map_version = ?
        WHERE r.rn = 1
        ORDER BY
            CASE WHEN r.chamber = 'Senate' THEN 1 ELSE 0 END,
            r.{district_col} NULLS LAST,
            r.full_name
        """,
        [map_version],
    ).fetchall()
    cols = [
        "bioguide_id",
        "full_name",
        "chamber",
        "party",
        "district_number",
        "partisan_lean",
        "is_target",
        "website",
    ]
    return [dict(zip(cols, r)) for r in rows]


def target_four(
    conn: duckdb.DuckDBPyConnection,
    *,
    map_version: str = "2026",
) -> list[dict[str, Any]]:
    require_map_version(map_version)
    members = list_delegation(conn, map_version=map_version)
    targets = [
        m
        for m in members
        if m["chamber"] == "House" and m["district_number"] in TARGET_DISTRICTS_2026
    ]
    # Prefer is_target from dim_district; fall back to TARGET_DISTRICTS_2026.
    if any(m.get("is_target") for m in members if m["chamber"] == "House"):
        targets = [
            m
            for m in members
            if m["chamber"] == "House" and m.get("is_target")
        ]
    targets.sort(key=lambda m: m["district_number"] or 0)
    return targets


def _tag_record_sql() -> str:
    # Live Yea/Nay counts on RULE/HUMAN tags only (no naked LLM).
    return """
        SELECT
            m.bioguide_id,
            i.impact_tag,
            sum(CASE WHEN m.position = 'YEA' THEN 1 ELSE 0 END) AS yea_n,
            sum(CASE WHEN m.position = 'NAY' THEN 1 ELSE 0 END) AS nay_n
        FROM fact_member_vote m
        JOIN fact_vote v ON v.vote_id = m.vote_id
        JOIN bridge_vote_impact i ON i.vote_id = v.vote_id
        WHERE i.classified_by IN ('RULE', 'HUMAN')
          AND i.impact_tag = ?
          AND m.bioguide_id = ?
          AND v.vote_category NOT IN ('NOMINATION', 'CLOTURE')
        GROUP BY 1, 2
    """


def member_scorecard_row(
    conn: duckdb.DuckDBPyConnection,
    member: dict[str, Any],
    *,
    tags: tuple[str, ...] = SCORECARD_TAGS,
) -> dict[str, Any]:
    row = {
        "bioguide_id": member["bioguide_id"],
        "full_name": member["full_name"],
        "chamber": member["chamber"],
        "party": member["party"],
        "district_number": member.get("district_number"),
        "partisan_lean": member.get("partisan_lean"),
        "is_target": member.get("is_target"),
        "map_version": "2026",
    }
    for tag in tags:
        hit = conn.execute(
            _tag_record_sql(),
            [tag, member["bioguide_id"]],
        ).fetchone()
        if hit is None:
            row[f"{tag}_yea"] = 0
            row[f"{tag}_nay"] = 0
            row[tag] = "—"
        else:
            yea_n, nay_n = int(hit[2]), int(hit[3])
            row[f"{tag}_yea"] = yea_n
            row[f"{tag}_nay"] = nay_n
            row[tag] = f"{yea_n}Y / {nay_n}N"
    return row


def scorecard_rows(
    conn: duckdb.DuckDBPyConnection,
    members: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [member_scorecard_row(conn, m) for m in members]


def district_votes_for_member(
    conn: duckdb.DuckDBPyConnection,
    *,
    bioguide_id: str,
    limit: int = DISTRICT_PAGE_MAX_VOTES,
) -> list[dict[str, Any]]:
    """
    Activist-facing votes for one member.

    Requires plain_language_summary; excludes suppressed categories and naked LLM.
    Raises if a selected row somehow lacks a summary (defense in depth).
    """
    suppressed = sorted(SITE_SUPPRESSED_CATEGORIES)
    placeholders = ", ".join("?" for _ in suppressed)
    sql = f"""
        SELECT
            v.vote_id,
            v.vote_date,
            v.chamber,
            v.vote_category,
            v.bill_id,
            v.source_url,
            b.plain_language_summary,
            m.position,
            list(DISTINCT i.impact_tag ORDER BY i.impact_tag) AS tags
        FROM fact_member_vote m
        JOIN fact_vote v ON v.vote_id = m.vote_id
        JOIN dim_bill b ON b.bill_id = v.bill_id
        JOIN bridge_vote_impact i ON i.vote_id = v.vote_id
        WHERE m.bioguide_id = ?
          AND v.vote_category NOT IN ({placeholders})
          AND b.plain_language_summary IS NOT NULL
          AND length(trim(b.plain_language_summary)) > 0
          AND i.classified_by IN ('RULE', 'HUMAN')
          AND NOT EXISTS (
              SELECT 1 FROM bridge_vote_impact llm
              WHERE llm.vote_id = v.vote_id AND llm.classified_by = 'LLM'
          )
        GROUP BY 1, 2, 3, 4, 5, 6, 7, 8
        ORDER BY v.vote_date DESC, v.vote_id
        LIMIT ?
    """
    rows = conn.execute(
        sql, [bioguide_id, *suppressed, limit]
    ).fetchall()
    cols = [
        "vote_id",
        "vote_date",
        "chamber",
        "vote_category",
        "bill_id",
        "source_url",
        "plain_language_summary",
        "position",
        "tags",
    ]
    out = []
    for r in rows:
        item = dict(zip(cols, r))
        if not item["plain_language_summary"] or not str(item["plain_language_summary"]).strip():
            raise RuntimeError(
                f"refusing to render {item['vote_id']}: null plain_language_summary "
                "(never fall back to vote_question)"
            )
        if item["vote_category"] in SITE_SUPPRESSED_CATEGORIES:
            raise RuntimeError(
                f"refusing to render suppressed category on district page: "
                f"{item['vote_id']} {item['vote_category']}"
            )
        out.append(item)
    return out


def vote_detail_audit_rows(conn: duckdb.DuckDBPyConnection) -> list[list[Any]]:
    """
    Flattened audit trail for Sheets Vote Detail.

    Excludes unadjudicated LLM tags and the review queue. Summaries may be blank
    on the audit surface (unlike the activist site).
    """
    rows = conn.execute(
        """
        SELECT
            l.full_name,
            l.party,
            coalesce(cast(l.district_2026 AS VARCHAR), 'Senate') AS district,
            v.vote_date,
            coalesce(v.bill_id, '') AS bill_id,
            coalesce(b.plain_language_summary, '') AS plain_language_summary,
            m.position,
            string_agg(DISTINCT i.impact_tag, ', ' ORDER BY i.impact_tag) AS tags,
            coalesce(v.source_url, '') AS source_url
        FROM fact_member_vote m
        JOIN fact_vote v ON v.vote_id = m.vote_id
        JOIN bridge_vote_impact i ON i.vote_id = v.vote_id
        JOIN dim_legislator l
          ON l.bioguide_id = m.bioguide_id
         AND l.term_start <= v.vote_date
         AND v.vote_date < l.term_end
        LEFT JOIN dim_bill b ON b.bill_id = v.bill_id
        WHERE i.classified_by IN ('RULE', 'HUMAN')
          AND l.state = 'VA'
        GROUP BY 1, 2, 3, 4, 5, 6, 7, 9
        ORDER BY v.vote_date DESC, l.full_name
        """
    ).fetchall()
    return [list(r) for r in rows]
