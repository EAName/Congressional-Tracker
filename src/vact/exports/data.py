"""Live warehouse queries for Sheets audit and activist-facing publication."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import duckdb

from vact.transforms.districts import TARGET_DISTRICTS_2026, require_map_version

# District / social surfaces (broader suppression than scorecard math).
SITE_SUPPRESSED_CATEGORIES = frozenset(
    {
        "PROCEDURAL",
        "CLOTURE",
        "NOMINATION",
        "SUSPENSION",
        "MOTION_TO_RECOMMIT",
    }
)

# Scorecard / heatmap aggregation (FIX 1). SUSPENSION remains eligible and ranks
# below PASSAGE when resolving one position per bill.
SCORECARD_SUPPRESSED_CATEGORIES = frozenset(
    {
        "PROCEDURAL",
        "CLOTURE",
        "NOMINATION",
        "MOTION_TO_RECOMMIT",
    }
)
SCORECARD_SUPPRESSED_BILL_TYPES = frozenset({"hres", "sres"})

# Publication surfaces show all seven tags (FIX 3). Never render an em dash.
SCORECARD_TAGS = (
    "ACCESS_TO_CAPITAL",
    "TAX_BURDEN",
    "FEDERAL_CONTRACTING",
    "HEALTH_COSTS",
    "INPUT_COSTS",
    "REGULATORY_BURDEN",
    "WORKFORCE",
)
SITE_SCORECARD_TAGS = SCORECARD_TAGS
ALL_IMPACT_TAGS = SCORECARD_TAGS

EMPTY_SCORE_LABEL = "no tagged votes"

CATEGORY_DISPLAY = {
    "PROCEDURAL": "Procedural",
    "CLOTURE": "Cloture",
    "PASSAGE": "Passage",
    "NOMINATION": "Nomination",
    "AMENDMENT": "Amendment",
    "SUSPENSION": "Suspension",
    "MOTION_TO_RECOMMIT": "Motion to recommit",
}

DISTRICT_PAGE_MAX_VOTES = 5

# PASSAGE > SUSPENSION > AMENDMENT for per-bill position resolve (FIX 2).
_SUBSTANCE_RANK_SQL = """
    CASE v.vote_category
      WHEN 'PASSAGE' THEN 3
      WHEN 'SUSPENSION' THEN 2
      WHEN 'AMENDMENT' THEN 1
      ELSE 0
    END
"""


def display_category(raw: str) -> str:
    return CATEGORY_DISPLAY.get(raw, raw.replace("_", " ").title())


def display_tag(raw: str) -> str:
    return raw.replace("_", " ").title()


def format_score_cell(yea: int, nay: int) -> str:
    bills = yea + nay
    if bills == 0:
        return EMPTY_SCORE_LABEL
    return f"{yea}Y / {nay}N of {bills} bills"


def generated_at_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def corpus_vote_count(conn: duckdb.DuckDBPyConnection) -> int:
    row = conn.execute("SELECT count(*) FROM fact_vote").fetchone()
    return int(row[0]) if row else 0


def vote_category_mix(conn: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    """Live counts of fact_vote.vote_category (pipeline telemetry / README)."""
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


def _scorecard_eligibility_sql(*, alias_vote: str = "v", alias_bill: str = "b") -> str:
    cats = ", ".join(f"'{c}'" for c in sorted(SCORECARD_SUPPRESSED_CATEGORIES))
    types = ", ".join(f"'{t}'" for t in sorted(SCORECARD_SUPPRESSED_BILL_TYPES))
    rank = _SUBSTANCE_RANK_SQL.replace("v.", f"{alias_vote}.")
    return f"""
        {alias_vote}.vote_category NOT IN ({cats})
        AND coalesce({alias_bill}.bill_type, '') NOT IN ({types})
        AND {alias_vote}.bill_id IS NOT NULL
        AND ({rank}) > 0
    """


def distinct_substantive_bill_count(conn: duckdb.DuckDBPyConnection) -> int:
    """Distinct bills that survive scorecard suppression and have a RULE/HUMAN tag."""
    row = conn.execute(
        f"""
        SELECT count(DISTINCT v.bill_id)
        FROM fact_vote v
        JOIN dim_bill b ON b.bill_id = v.bill_id
        JOIN bridge_vote_impact i ON i.vote_id = v.vote_id
        WHERE i.classified_by IN ('RULE', 'HUMAN')
          AND {_scorecard_eligibility_sql()}
        """
    ).fetchone()
    return int(row[0]) if row else 0


def bills_missing_summary_count(conn: duckdb.DuckDBPyConnection) -> int:
    """Distinct scorecard-eligible tagged bills without a plain_language_summary."""
    row = conn.execute(
        f"""
        SELECT count(DISTINCT v.bill_id)
        FROM fact_vote v
        JOIN dim_bill b ON b.bill_id = v.bill_id
        JOIN bridge_vote_impact i ON i.vote_id = v.vote_id
        WHERE i.classified_by IN ('RULE', 'HUMAN')
          AND {_scorecard_eligibility_sql()}
          AND (
                b.plain_language_summary IS NULL
             OR length(trim(b.plain_language_summary)) = 0
          )
        """
    ).fetchone()
    return int(row[0]) if row else 0


def publication_ready_bill_count(conn: duckdb.DuckDBPyConnection) -> int:
    """Distinct scorecard-eligible tagged bills with a human plain_language_summary."""
    row = conn.execute(
        f"""
        SELECT count(DISTINCT v.bill_id)
        FROM fact_vote v
        JOIN dim_bill b ON b.bill_id = v.bill_id
        JOIN bridge_vote_impact i ON i.vote_id = v.vote_id
        WHERE i.classified_by IN ('RULE', 'HUMAN')
          AND {_scorecard_eligibility_sql()}
          AND b.plain_language_summary IS NOT NULL
          AND length(trim(b.plain_language_summary)) > 0
          AND NOT EXISTS (
              SELECT 1 FROM bridge_vote_impact llm
              WHERE llm.vote_id = v.vote_id AND llm.classified_by = 'LLM'
          )
        """
    ).fetchone()
    return int(row[0]) if row else 0


def publication_ready_count(conn: duckdb.DuckDBPyConnection) -> int:
    """Backward-compatible alias: publication-ready distinct bills."""
    return publication_ready_bill_count(conn)


def party_line_split_count(conn: duckdb.DuckDBPyConnection) -> int:
    """Count of party-line VA splits on tagged substantive roll calls."""
    from vact.pipeline.notify import find_party_line_splits

    return len(find_party_line_splits(conn))


def tag_coverage_gaps(
    conn: duckdb.DuckDBPyConnection,
    *,
    min_bills: int = 3,
    tags: tuple[str, ...] = SCORECARD_TAGS,
) -> list[dict[str, Any]]:
    """Tags with fewer than min_bills distinct scorecard-eligible bills."""
    out = []
    for tag in tags:
        row = conn.execute(
            f"""
            SELECT count(DISTINCT v.bill_id)
            FROM fact_vote v
            JOIN dim_bill b ON b.bill_id = v.bill_id
            JOIN bridge_vote_impact i ON i.vote_id = v.vote_id
            WHERE i.classified_by IN ('RULE', 'HUMAN')
              AND i.impact_tag = ?
              AND {_scorecard_eligibility_sql()}
            """,
            [tag],
        ).fetchone()
        n = int(row[0]) if row else 0
        if n < min_bills:
            out.append({"tag": tag, "bills": n, "label": display_tag(tag)})
    return out


def heatmap_cell(yea: int, nay: int) -> dict[str, Any]:
    """Encode a scorecard cell for CSS heatmap rendering (bill-level counts)."""
    bills = yea + nay
    if bills == 0:
        return {
            "label": EMPTY_SCORE_LABEL,
            "yea": 0,
            "nay": 0,
            "bills": 0,
            "tone": "empty",
            "pct_yea": None,
        }
    pct = yea / bills
    if pct >= 0.7:
        tone = "yea-heavy"
    elif pct <= 0.3:
        tone = "nay-heavy"
    else:
        tone = "split"
    return {
        "label": format_score_cell(yea, nay),
        "yea": yea,
        "nay": nay,
        "bills": bills,
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
    if any(m.get("is_target") for m in members if m["chamber"] == "House"):
        targets = [
            m
            for m in members
            if m["chamber"] == "House" and m.get("is_target")
        ]
    targets.sort(key=lambda m: m["district_number"] or 0)
    return targets


def _tag_record_sql() -> str:
    """
    Bill-level Yea/Nay for one member and impact tag.

    One surviving roll call per bill: PASSAGE > SUSPENSION > AMENDMENT,
    then latest vote_date. Procedural / cloture / nomination / MTR and
    hres/sres never enter the denominator.
    """
    return f"""
        WITH eligible AS (
            SELECT
                m.bioguide_id,
                i.impact_tag,
                v.bill_id,
                v.vote_id,
                v.vote_date,
                m.position,
                {_SUBSTANCE_RANK_SQL} AS substance_rank
            FROM fact_member_vote m
            JOIN fact_vote v ON v.vote_id = m.vote_id
            JOIN dim_bill b ON b.bill_id = v.bill_id
            JOIN bridge_vote_impact i ON i.vote_id = v.vote_id
            WHERE i.classified_by IN ('RULE', 'HUMAN')
              AND i.impact_tag = ?
              AND m.bioguide_id = ?
              AND m.position IN ('YEA', 'NAY')
              AND {_scorecard_eligibility_sql()}
        ),
        ranked AS (
            SELECT
                *,
                row_number() OVER (
                    PARTITION BY bioguide_id, impact_tag, bill_id
                    ORDER BY substance_rank DESC, vote_date DESC, vote_id DESC
                ) AS rn
            FROM eligible
        )
        SELECT
            bioguide_id,
            impact_tag,
            sum(CASE WHEN position = 'YEA' THEN 1 ELSE 0 END) AS yea_n,
            sum(CASE WHEN position = 'NAY' THEN 1 ELSE 0 END) AS nay_n,
            count(*) AS bills_n
        FROM ranked
        WHERE rn = 1
        GROUP BY 1, 2
    """


def _member_bills_counted_sql() -> str:
    """Distinct bills contributing to any scorecard tag for one member."""
    return f"""
        WITH eligible AS (
            SELECT
                v.bill_id,
                {_SUBSTANCE_RANK_SQL} AS substance_rank,
                v.vote_date,
                v.vote_id
            FROM fact_member_vote m
            JOIN fact_vote v ON v.vote_id = m.vote_id
            JOIN dim_bill b ON b.bill_id = v.bill_id
            JOIN bridge_vote_impact i ON i.vote_id = v.vote_id
            WHERE i.classified_by IN ('RULE', 'HUMAN')
              AND m.bioguide_id = ?
              AND m.position IN ('YEA', 'NAY')
              AND {_scorecard_eligibility_sql()}
        ),
        ranked AS (
            SELECT
                bill_id,
                row_number() OVER (
                    PARTITION BY bill_id
                    ORDER BY substance_rank DESC, vote_date DESC, vote_id DESC
                ) AS rn
            FROM eligible
        )
        SELECT count(*) FROM ranked WHERE rn = 1
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
            yea_n = nay_n = bills_n = 0
        else:
            yea_n, nay_n, bills_n = int(hit[2]), int(hit[3]), int(hit[4])
        row[f"{tag}_yea"] = yea_n
        row[f"{tag}_nay"] = nay_n
        row[f"{tag}_bills"] = bills_n
        row[tag] = format_score_cell(yea_n, nay_n)
    bills = conn.execute(
        _member_bills_counted_sql(), [member["bioguide_id"]]
    ).fetchone()
    row["bills_counted"] = int(bills[0]) if bills else 0
    return row


def scorecard_rows(
    conn: duckdb.DuckDBPyConnection,
    members: list[dict[str, Any]],
    *,
    tags: tuple[str, ...] = SCORECARD_TAGS,
) -> list[dict[str, Any]]:
    return [member_scorecard_row(conn, m, tags=tags) for m in members]


def assert_scorecard_excludes_suppressed(conn: duckdb.DuckDBPyConnection) -> None:
    """
    Hard check: no scorecard-eligible row may carry a suppressed category or bill type.

    Used by pytest. Raises AssertionError with sample rows on failure.
    """
    cats = sorted(SCORECARD_SUPPRESSED_CATEGORIES)
    types = sorted(SCORECARD_SUPPRESSED_BILL_TYPES)
    bad_cat = conn.execute(
        f"""
        SELECT v.vote_id, v.vote_category, b.bill_type
        FROM fact_vote v
        JOIN dim_bill b ON b.bill_id = v.bill_id
        WHERE {_scorecard_eligibility_sql()}
          AND v.vote_category IN ({", ".join("?" for _ in cats)})
        LIMIT 5
        """,
        cats,
    ).fetchall()
    if bad_cat:
        raise AssertionError(
            f"suppressed categories leaked into scorecard eligibility: {bad_cat}"
        )
    bad_type = conn.execute(
        f"""
        SELECT v.vote_id, v.vote_category, b.bill_type
        FROM fact_vote v
        JOIN dim_bill b ON b.bill_id = v.bill_id
        WHERE {_scorecard_eligibility_sql()}
          AND coalesce(b.bill_type, '') IN ({", ".join("?" for _ in types)})
        LIMIT 5
        """,
        types,
    ).fetchall()
    if bad_type:
        raise AssertionError(
            f"suppressed bill types leaked into scorecard eligibility: {bad_type}"
        )

    leaked = conn.execute(
        f"""
        WITH eligible AS (
            SELECT
                v.vote_id,
                v.vote_category,
                b.bill_type,
                {_SUBSTANCE_RANK_SQL} AS substance_rank
            FROM fact_member_vote m
            JOIN fact_vote v ON v.vote_id = m.vote_id
            JOIN dim_bill b ON b.bill_id = v.bill_id
            JOIN bridge_vote_impact i ON i.vote_id = v.vote_id
            WHERE i.classified_by IN ('RULE', 'HUMAN')
              AND m.position IN ('YEA', 'NAY')
              AND {_scorecard_eligibility_sql()}
        )
        SELECT vote_id, vote_category, bill_type
        FROM eligible
        WHERE vote_category IN ({", ".join("?" for _ in cats)})
           OR coalesce(bill_type, '') IN ({", ".join("?" for _ in types)})
           OR substance_rank = 0
        LIMIT 5
        """,
        [*cats, *types],
    ).fetchall()
    if leaked:
        raise AssertionError(
            f"scorecard eligible CTE leaked suppressed rows: {leaked}"
        )


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
