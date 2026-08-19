"""Signed scoring frame: valence storage, the scoreable filter, and the score math.

This is the base-pack substrate every downstream analysis prompt (within-party
deviations, IRT, target model, briefs) consumes. Three pieces:

1. Valence      — persisted political judgment (does a YEA advance the axis?),
                  keyed on (vote_id, impact_tag) in fact_vote_valence.
2. Scoreable    — the filter that admits only substantive, valence-adjudicated
                  (vote, tag) pairs into a score (procedural noise never enters).
3. Signed score — per (member, theme): a live [-1, +1] estimate with a Wilson
                  band, raw counts, n_contested, and a `sufficient` flag.

No signed score is ever stored; the frame is rebuilt live on every call from
either the warehouse SQL path or `data/votes.csv` (Prompt 1). Only valence is
persisted, and only as adjudicated input.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

import duckdb
import structlog
import yaml

from vact.paths import REPO_ROOT
from vact.transforms.districts import require_map_version
from vact.warehouse.connection import connect, ensure_schema

logger = structlog.get_logger(__name__)

SCORING_CONFIG_PATH = REPO_ROOT / "config" / "scoring.yaml"

VALENCE_SOURCES = ("RULE", "LLM", "HUMAN")
CONTESTED_POSITIONS = ("YEA", "NAY")


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ScoringConfig:
    version: int
    axis_name: str
    axis_description: str
    include_categories: frozenset[str]
    exclude_categories: frozenset[str]
    min_contested: int
    wilson_z: float
    min_eligible_for_display: int
    deviation_baseline: str = "weighted_median"
    min_defection_votes: int = 1
    exclude_rule_resolutions: bool = True
    rule_resolution_bill_types: frozenset[str] = frozenset({"hres", "sres"})
    rule_resolution_title_pattern: str | None = r"(?i)^\s*providing for consideration"
    # tag -> list of (compiled pattern, valence) proposal rules
    valence_rules: dict[str, list[tuple[re.Pattern[str], int]]] = field(default_factory=dict)


def load_scoring_config(path: Path | None = None) -> ScoringConfig:
    cfg_path = path or SCORING_CONFIG_PATH
    payload = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}

    axis = payload.get("axis") or {}
    scoreable = payload.get("scoreable") or {}
    sufficiency = payload.get("sufficiency") or {}
    wilson = payload.get("wilson") or {}
    analysis = payload.get("analysis") or {}

    valence_rules: dict[str, list[tuple[re.Pattern[str], int]]] = {}
    for tag, entries in (payload.get("valence_rules") or {}).items():
        compiled: list[tuple[re.Pattern[str], int]] = []
        for entry in entries or []:
            valence = int(entry["valence"])
            if valence not in (-1, 1):
                raise ValueError(f"valence_rules[{tag}] valence must be -1 or 1, got {valence}")
            compiled.append((re.compile(str(entry["pattern"]), re.IGNORECASE), valence))
        valence_rules[tag] = compiled

    include = frozenset(scoreable.get("include_categories") or [])
    exclude = frozenset(scoreable.get("exclude_categories") or [])
    if not include:
        raise ValueError("scoring.yaml: scoreable.include_categories must be non-empty")
    overlap = include & exclude
    if overlap:
        raise ValueError(f"scoring.yaml: categories in both include and exclude: {sorted(overlap)}")

    exclude_rules = bool(scoreable.get("exclude_rule_resolutions", True))
    rule_types = frozenset(scoreable.get("rule_resolution_bill_types") or ["hres", "sres"])
    rule_pattern = scoreable.get("rule_resolution_title_pattern")

    deviations = analysis.get("deviations") or {}

    return ScoringConfig(
        version=int(payload.get("version") or 1),
        axis_name=str(axis.get("name") or "axis"),
        axis_description=str(axis.get("description") or "").strip(),
        include_categories=include,
        exclude_categories=exclude,
        min_contested=int(sufficiency.get("min_contested") or 3),
        wilson_z=float(wilson.get("z") or 1.96),
        min_eligible_for_display=int(analysis.get("min_eligible_for_display") or 3),
        deviation_baseline=str(deviations.get("baseline") or "weighted_median"),
        min_defection_votes=int(deviations.get("min_defection_votes") or 1),
        exclude_rule_resolutions=exclude_rules,
        rule_resolution_bill_types=rule_types,
        rule_resolution_title_pattern=str(rule_pattern) if rule_pattern else None,
        valence_rules=valence_rules,
    )


def _rule_resolution_exclusion(config: ScoringConfig) -> tuple[str, list[Any]]:
    """SQL predicate + params dropping special-rule resolutions from the scoreable set.

    Returns a fragment like ``AND NOT (b.bill_type IN (...) AND regexp_matches(...))``
    that assumes a ``dim_bill b`` join is present, plus the bound params. Empty when
    disabled. Shared by scoreable_pairs() and the frame SQL so both stay consistent.
    """
    if (
        not config.exclude_rule_resolutions
        or not config.rule_resolution_bill_types
        or not config.rule_resolution_title_pattern
    ):
        return ("", [])
    bill_types = sorted(config.rule_resolution_bill_types)
    ph = ", ".join("?" for _ in bill_types)
    clause = (
        f"AND NOT (b.bill_type IN ({ph}) "
        "AND regexp_matches(coalesce(b.title, ''), ?))"
    )
    return (clause, [*bill_types, config.rule_resolution_title_pattern])


# --------------------------------------------------------------------------- #
# Wilson score interval + signed-score math (pure, no scipy)
# --------------------------------------------------------------------------- #
def wilson_interval(k: int, n: int, z: float) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion k/n. Returns (low, high).

    Degenerate n == 0 yields (0.0, 1.0): no information, maximal uncertainty.
    """
    if n <= 0:
        return (0.0, 1.0)
    p = k / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    half = (z / denom) * math.sqrt(p * (1.0 - p) / n + z2 / (4 * n * n))
    low = max(0.0, center - half)
    high = min(1.0, center + half)
    return (low, high)


def signed_score_from_counts(n_pro: int, n_contested: int, z: float) -> dict[str, float | None]:
    """Map pro-axis counts to a signed score in [-1, +1] with a Wilson band.

    p = share of contested votes where the member advanced the axis.
    signed = 2p - 1  (so 0 = neutral, +1 = always pro, -1 = always anti).
    The band is the Wilson interval on p, mapped through the same 2x-1 transform.
    """
    if n_contested <= 0:
        return {"signed_score": None, "wilson_low": None, "wilson_high": None, "p_pro": None}
    p = n_pro / n_contested
    low, high = wilson_interval(n_pro, n_contested, z)
    return {
        "signed_score": round(2.0 * p - 1.0, 4),
        "wilson_low": round(2.0 * low - 1.0, 4),
        "wilson_high": round(2.0 * high - 1.0, 4),
        "p_pro": round(p, 4),
    }


# --------------------------------------------------------------------------- #
# Valence storage
# --------------------------------------------------------------------------- #
def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def set_valence(
    conn: duckdb.DuckDBPyConnection,
    *,
    vote_id: str,
    impact_tag: str,
    valence: int,
    source: str,
) -> None:
    """Upsert one adjudicated valence row. source in RULE|LLM|HUMAN."""
    if valence not in (-1, 0, 1):
        raise ValueError(f"valence must be -1, 0, or 1; got {valence}")
    if source not in VALENCE_SOURCES:
        raise ValueError(f"valence source must be one of {VALENCE_SOURCES}; got {source!r}")
    conn.execute(
        """
        INSERT INTO fact_vote_valence
            (vote_id, impact_tag, valence, valence_source, adjudicated_at_utc)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (vote_id, impact_tag) DO UPDATE SET
            valence = excluded.valence,
            valence_source = excluded.valence_source,
            adjudicated_at_utc = excluded.adjudicated_at_utc
        """,
        [vote_id, impact_tag, int(valence), source, _now_iso()],
    )


def load_valence(conn: duckdb.DuckDBPyConnection) -> dict[tuple[str, str], tuple[int, str]]:
    """Return {(vote_id, impact_tag): (valence, source)} for every adjudicated pair."""
    rows = conn.execute(
        "SELECT vote_id, impact_tag, valence, valence_source FROM fact_vote_valence"
    ).fetchall()
    return {(r[0], r[1]): (int(r[2]), r[3]) for r in rows}


def propose_valence(
    conn: duckdb.DuckDBPyConnection,
    config: ScoringConfig,
    *,
    new_only: bool = True,
) -> dict[str, int]:
    """Write RULE-proposed valence for scoreable-category tagged votes.

    PROPOSALS ONLY. These are written with valence_source='RULE' and must be
    reviewed and re-set as HUMAN before a scorecard is published — exactly like
    LLM impact tags. Only (vote, tag) pairs matching a config valence_rule are
    proposed; ambiguous or unmatched pairs are left for a human. When new_only,
    pairs that already carry any valence (including a prior HUMAN one) are skipped.
    """
    existing = set(load_valence(conn)) if new_only else set()
    include = sorted(config.include_categories)
    ph = ", ".join("?" for _ in include)
    rows = conn.execute(
        f"""
        SELECT
            i.vote_id,
            i.impact_tag,
            concat_ws(' || ',
                v.vote_question, b.title, b.short_title, b.policy_area
            ) AS corpus
        FROM bridge_vote_impact i
        JOIN fact_vote v ON v.vote_id = i.vote_id
        LEFT JOIN dim_bill b ON b.bill_id = v.bill_id
        WHERE i.classified_by IN ('RULE', 'HUMAN')
          AND v.vote_category IN ({ph})
        """,
        include,
    ).fetchall()

    proposed = 0
    skipped_existing = 0
    unmatched = 0
    for vote_id, impact_tag, corpus in rows:
        if new_only and (vote_id, impact_tag) in existing:
            skipped_existing += 1
            continue
        valence = _match_valence(config, impact_tag, corpus or "")
        if valence is None:
            unmatched += 1
            continue
        set_valence(conn, vote_id=vote_id, impact_tag=impact_tag, valence=valence, source="RULE")
        proposed += 1

    logger.info(
        "valence.propose",
        proposed=proposed,
        skipped_existing=skipped_existing,
        unmatched=unmatched,
    )
    return {"proposed": proposed, "skipped_existing": skipped_existing, "unmatched": unmatched}


def _match_valence(config: ScoringConfig, impact_tag: str, corpus: str) -> int | None:
    """First matching rule wins. None means no confident proposal (leave to human)."""
    for pattern, valence in config.valence_rules.get(impact_tag, []):
        if pattern.search(corpus):
            return valence
    return None


# --------------------------------------------------------------------------- #
# Scoreable filter (base-pack Prompt 3/4 substrate)
# --------------------------------------------------------------------------- #
def scoreable_pairs(
    conn: duckdb.DuckDBPyConnection,
    config: ScoringConfig,
) -> list[dict[str, Any]]:
    """The scoreable universe: (vote_id, impact_tag, valence, valence_source).

    A pair is scoreable iff the vote_category is included AND an adjudicated
    valence of +/-1 exists. This is the single filter the deviation report and
    the IRT model both reuse so procedural votes never enter either likelihood.
    """
    include = sorted(config.include_categories)
    ph = ", ".join("?" for _ in include)
    rule_clause, rule_params = _rule_resolution_exclusion(config)
    rows = conn.execute(
        f"""
        SELECT
            fv.vote_id,
            fv.impact_tag,
            fv.valence,
            fv.valence_source
        FROM fact_vote_valence fv
        JOIN fact_vote v ON v.vote_id = fv.vote_id
        LEFT JOIN dim_bill b ON b.bill_id = v.bill_id
        WHERE fv.valence IN (-1, 1)
          AND v.vote_category IN ({ph})
          {rule_clause}
        ORDER BY fv.impact_tag, fv.vote_id
        """,
        [*include, *rule_params],
    ).fetchall()
    return [
        {"vote_id": r[0], "impact_tag": r[1], "valence": int(r[2]), "valence_source": r[3]}
        for r in rows
    ]


# --------------------------------------------------------------------------- #
# The signed scoring frame
# --------------------------------------------------------------------------- #
_FRAME_SQL = """
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
        fv.impact_tag,
        fv.valence
    FROM fact_vote_valence fv
    JOIN fact_vote v ON v.vote_id = fv.vote_id
    LEFT JOIN dim_bill b ON b.bill_id = v.bill_id
    WHERE fv.valence IN (-1, 1)
      AND v.vote_category IN ({category_ph})
      {rule_clause}
)
SELECT
    m.bioguide_id,
    m.full_name,
    m.chamber,
    m.party,
    m.district_number,
    s.impact_tag,
    count(*) FILTER (WHERE mv.position IN ('YEA', 'NAY'))                       AS n_contested,
    count(*) FILTER (WHERE mv.position = 'YEA')                                 AS n_yea,
    count(*) FILTER (WHERE mv.position = 'NAY')                                 AS n_nay,
    count(*) FILTER (WHERE mv.position = 'NOT_VOTING')                          AS n_not_voting,
    count(*) FILTER (WHERE mv.position = 'PRESENT')                             AS n_present,
    count(*) FILTER (
        WHERE (mv.position = 'YEA' AND s.valence = 1)
           OR (mv.position = 'NAY' AND s.valence = -1)
    )                                                                          AS n_pro
FROM members m
JOIN scoreable s ON TRUE
JOIN fact_member_vote mv
     ON mv.vote_id = s.vote_id
    AND mv.bioguide_id = m.bioguide_id
GROUP BY 1, 2, 3, 4, 5, 6
HAVING count(*) FILTER (WHERE mv.position IN ('YEA', 'NAY', 'NOT_VOTING', 'PRESENT')) > 0
ORDER BY s.impact_tag, m.full_name
"""


def _finalize_frame_records(
    records: list[dict[str, Any]],
    config: ScoringConfig,
    *,
    map_version: str,
) -> list[dict[str, Any]]:
    """Attach signed score, Wilson band, sufficient, absence_rate. Never persist."""
    frame: list[dict[str, Any]] = []
    count_keys = ("n_contested", "n_yea", "n_nay", "n_not_voting", "n_present", "n_pro")
    for rec in records:
        for key in count_keys:
            rec[key] = int(rec[key] or 0)
        rec.update(signed_score_from_counts(rec["n_pro"], rec["n_contested"], config.wilson_z))
        rec["sufficient"] = rec["n_contested"] >= config.min_contested
        n_eligible = rec["n_contested"] + rec["n_not_voting"] + rec["n_present"]
        rec["absence_rate"] = (
            round(rec["n_not_voting"] / n_eligible, 4) if n_eligible else None
        )
        rec["map_version"] = map_version
        frame.append(rec)
    return frame


def frame_from_vote_rows(
    rows: Sequence[Any],
    config: ScoringConfig | None = None,
    *,
    map_version: str = "2021",
) -> list[dict[str, Any]]:
    """Build the signed scoring frame from VoteRow-like records (votes.csv path).

    Same math as the warehouse SQL path. Group grain is (bioguide_id, theme).
    """
    require_map_version(map_version)
    cfg = config or load_scoring_config()
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        bio = row.member_bioguide_id
        theme = row.theme
        key = (bio, theme)
        rec = grouped.get(key)
        if rec is None:
            rec = {
                "bioguide_id": bio,
                "full_name": row.member_name,
                "chamber": row.chamber,
                "party": row.party or None,
                "district_number": row.district_number,
                "impact_tag": theme,
                "n_contested": 0,
                "n_yea": 0,
                "n_nay": 0,
                "n_not_voting": 0,
                "n_present": 0,
                "n_pro": 0,
            }
            grouped[key] = rec
        cast = row.vote_cast.value if hasattr(row.vote_cast, "value") else str(row.vote_cast)
        if cast == "yea":
            rec["n_yea"] += 1
            rec["n_contested"] += 1
            if row.valence == 1:
                rec["n_pro"] += 1
        elif cast == "nay":
            rec["n_nay"] += 1
            rec["n_contested"] += 1
            if row.valence == -1:
                rec["n_pro"] += 1
        elif cast == "not_voting":
            rec["n_not_voting"] += 1
        elif cast == "present":
            rec["n_present"] += 1
    records = [r for r in grouped.values() if (r["n_contested"] + r["n_not_voting"] + r["n_present"]) > 0]
    records.sort(key=lambda r: (r["impact_tag"], r["full_name"]))
    return _finalize_frame_records(records, cfg, map_version=map_version)


def build_scores_frame(
    conn: duckdb.DuckDBPyConnection | None = None,
    config: ScoringConfig | None = None,
    *,
    map_version: str = "2021",
    votes_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Compute the live signed scoring frame: one row per (member, theme).

    Never persisted. Each row carries raw counts, n_contested, the signed score
    with its Wilson band, an absence_rate, and the `sufficient` flag. Rows rest
    only on scoreable, valence-adjudicated votes; NOT_VOTING/PRESENT are counted
    as absences, never as an anti-axis position.

    `votes_path` selects the CSV reader (Prompt 1). Omit it for the warehouse
    SQL path used by tests and bootstrap.
    """
    require_map_version(map_version)
    cfg = config or load_scoring_config()
    if votes_path is not None:
        from vact.analysis.votes import validate_votes_csv

        rows = validate_votes_csv(votes_path)
        return frame_from_vote_rows(rows, cfg, map_version=map_version)
    if conn is None:
        raise TypeError("conn is required when votes_path is omitted")

    district_col = "district_2025" if map_version == "2021" else "district_2026"
    category_ph = ", ".join("?" for _ in sorted(cfg.include_categories))
    rule_clause, rule_params = _rule_resolution_exclusion(cfg)
    sql = _FRAME_SQL.format(
        district_col=district_col, category_ph=category_ph, rule_clause=rule_clause
    )

    rows = conn.execute(sql, [*sorted(cfg.include_categories), *rule_params]).fetchall()
    cols = [
        "bioguide_id",
        "full_name",
        "chamber",
        "party",
        "district_number",
        "impact_tag",
        "n_contested",
        "n_yea",
        "n_nay",
        "n_not_voting",
        "n_present",
        "n_pro",
    ]
    records = [dict(zip(cols, raw)) for raw in rows]
    return _finalize_frame_records(records, cfg, map_version=map_version)


def build_scores_frame_standalone(
    *,
    map_version: str = "2021",
    warehouse_path: Path | None = None,
    config_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Open the warehouse, ensure schema, and build the frame. CLI convenience."""
    conn = connect(warehouse_path)
    try:
        ensure_schema(conn)
        cfg = load_scoring_config(config_path)
        return build_scores_frame(conn, cfg, map_version=map_version)
    finally:
        conn.close()
