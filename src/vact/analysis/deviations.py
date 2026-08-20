"""Within-party deviation report (defection detection) — Prompt 9.

The politically useful signal is within-party variance, not the R-vs-D mirror.
Per theme this computes each caucus's baseline (weighted-median signed score
among sufficient members) and, for every member, the deviation from it plus the
specific roll calls driving it: votes where the member's axis-direction
(direction x valence) opposed their own party's majority on that same vote.

Absences never make a defection — NOT_VOTING/PRESENT are excluded from the
per-vote comparison and reported separately as absence_rate on the frame.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from vact.analysis.scoring import (
    ScoringConfig,
    _rule_resolution_exclusion,
    build_scores_frame,
    frame_from_vote_rows,
    load_scoring_config,
)
from vact.transforms.districts import require_map_version
from vact.warehouse.connection import connect, ensure_schema

REPORTS_DIR = Path("data") / "reports"


@dataclass(frozen=True)
class DefectionVote:
    vote_id: str
    vote_date: str
    bill_id: str | None
    plain_language_summary: str | None
    position: str  # YEA | NAY
    member_direction: int  # direction x valence for this member: +1 pro-axis, -1 anti
    party_majority_direction: int  # +1 / -1 the caucus went on this vote
    source_link: str | None


@dataclass(frozen=True)
class MemberThemeDeviation:
    bioguide_id: str
    full_name: str
    party: str | None
    chamber: str
    district_number: int | None
    impact_tag: str
    signed_score: float
    party_baseline: float
    deviation: float
    n_contested: int
    absence_rate: float | None
    defection_votes: tuple[DefectionVote, ...] = field(default_factory=tuple)


def weighted_median(pairs: list[tuple[float, float]]) -> float:
    """Lower weighted median of (value, weight) pairs. Empty → 0.0.

    Weight is n_contested — a member who voted on more of the theme's roll calls
    anchors the caucus baseline more than a barely-eligible one.
    """
    items = sorted((v, w) for v, w in pairs if w > 0)
    if not items:
        return 0.0
    total = sum(w for _, w in items)
    acc = 0.0
    for value, weight in items:
        acc += weight
        if acc >= total / 2:
            return value
    return items[-1][0]


def _aligned(position: str, valence: int) -> int:
    """direction x valence: +1 if the member advanced the axis on this vote, else -1."""
    direction = 1 if position == "YEA" else -1
    return direction * valence


_DETAIL_SQL = """
WITH active AS (
    SELECT *
    FROM dim_legislator
    WHERE is_incumbent
       OR (term_start <= current_date AND current_date < term_end)
),
members AS (
    SELECT bioguide_id, full_name, chamber, party, {district_col} AS district_number
    FROM (
        SELECT a.*, row_number() OVER (
            PARTITION BY a.bioguide_id ORDER BY a.term_start DESC
        ) AS rn
        FROM active a
    ) a
    WHERE a.rn = 1
),
scoreable AS (
    SELECT v.vote_id, fv.impact_tag, fv.valence
    FROM fact_vote_valence fv
    JOIN fact_vote v ON v.vote_id = fv.vote_id
    LEFT JOIN dim_bill b ON b.bill_id = v.bill_id
    WHERE fv.valence IN (-1, 1)
      AND v.vote_category IN ({category_ph})
      {rule_clause}
)
SELECT
    m.bioguide_id, m.full_name, m.party, m.chamber, m.district_number,
    s.impact_tag, s.vote_id, s.valence, mv.position,
    CAST(fv.vote_date AS VARCHAR) AS vote_date, fv.bill_id, fv.source_url,
    b.plain_language_summary
FROM members m
JOIN scoreable s ON TRUE
JOIN fact_member_vote mv ON mv.vote_id = s.vote_id AND mv.bioguide_id = m.bioguide_id
JOIN fact_vote fv ON fv.vote_id = s.vote_id
LEFT JOIN dim_bill b ON b.bill_id = fv.bill_id
WHERE mv.position IN ('YEA', 'NAY')
ORDER BY s.impact_tag, fv.vote_date, s.vote_id
"""


def _vote_level_rows(
    conn: duckdb.DuckDBPyConnection, config: ScoringConfig, *, map_version: str
) -> list[dict[str, Any]]:
    district_col = "district_2025" if map_version == "2021" else "district_2026"
    category_ph = ", ".join("?" for _ in sorted(config.include_categories))
    rule_clause, rule_params = _rule_resolution_exclusion(config)
    sql = _DETAIL_SQL.format(
        district_col=district_col, category_ph=category_ph, rule_clause=rule_clause
    )
    cols = [
        "bioguide_id", "full_name", "party", "chamber", "district_number",
        "impact_tag", "vote_id", "valence", "position",
        "vote_date", "bill_id", "source_url", "plain_language_summary",
    ]
    rows = conn.execute(sql, [*sorted(config.include_categories), *rule_params]).fetchall()
    out = []
    for raw in rows:
        rec = dict(zip(cols, raw))
        rec["valence"] = int(rec["valence"])
        rec["aligned"] = _aligned(rec["position"], rec["valence"])
        out.append(rec)
    return out


def _party_majority_by_vote(
    rows: list[dict[str, Any]],
) -> dict[tuple[str, str, str], int]:
    """(theme, vote_id, party) -> majority aligned direction (+1/-1/0 on a tie)."""
    tally: dict[tuple[str, str, str], list[int]] = {}
    for r in rows:
        if r["party"] is None:
            continue
        key = (r["impact_tag"], r["vote_id"], r["party"])
        tally.setdefault(key, [0, 0])
        if r["aligned"] > 0:
            tally[key][0] += 1
        else:
            tally[key][1] += 1
    out: dict[tuple[str, str, str], int] = {}
    for key, (pro, anti) in tally.items():
        out[key] = 1 if pro > anti else (-1 if anti > pro else 0)
    return out


def detail_from_vote_rows(rows: list[Any]) -> list[dict[str, Any]]:
    """Vote-level YEA/NAY rows for defection detection, from votes.csv."""
    out: list[dict[str, Any]] = []
    for row in rows:
        cast = row.vote_cast.value if hasattr(row.vote_cast, "value") else str(row.vote_cast)
        if cast not in {"yea", "nay"}:
            continue
        position = "YEA" if cast == "yea" else "NAY"
        valence = int(row.valence)
        out.append(
            {
                "bioguide_id": row.member_bioguide_id,
                "full_name": row.member_name,
                "party": row.party or None,
                "chamber": row.chamber,
                "district_number": row.district_number,
                "impact_tag": row.theme,
                "vote_id": row.rollcall_id,
                "valence": valence,
                "position": position,
                "vote_date": row.rollcall_date,
                "bill_id": row.bill_id or None,
                "source_url": row.source_url or None,
                "plain_language_summary": row.plain_language_summary or None,
                "aligned": _aligned(position, valence),
            }
        )
    return out


def _deviations_from_frame_and_detail(
    frame: list[dict[str, Any]],
    detail: list[dict[str, Any]],
    cfg: ScoringConfig,
) -> list[MemberThemeDeviation]:
    frame_by_key = {(r["bioguide_id"], r["impact_tag"]): r for r in frame}
    majority = _party_majority_by_vote(detail)

    baseline: dict[tuple[str, str], float] = {}
    by_theme_party: dict[tuple[str, str], list[tuple[float, float]]] = {}
    for r in frame:
        if not r["sufficient"] or r["party"] is None or r["signed_score"] is None:
            continue
        by_theme_party.setdefault((r["impact_tag"], r["party"]), []).append(
            (r["signed_score"], float(r["n_contested"]))
        )
    for key, pairs in by_theme_party.items():
        baseline[key] = weighted_median(pairs)

    defections: dict[tuple[str, str], list[DefectionVote]] = {}
    for r in detail:
        if r["party"] is None:
            continue
        maj = majority.get((r["impact_tag"], r["vote_id"], r["party"]), 0)
        if maj == 0 or r["aligned"] == maj:
            continue
        defections.setdefault((r["bioguide_id"], r["impact_tag"]), []).append(
            DefectionVote(
                vote_id=r["vote_id"],
                vote_date=r["vote_date"],
                bill_id=r["bill_id"],
                plain_language_summary=r["plain_language_summary"],
                position=r["position"],
                member_direction=r["aligned"],
                party_majority_direction=maj,
                source_link=r["source_url"],
            )
        )

    results: list[MemberThemeDeviation] = []
    for (bioguide, theme), fr in frame_by_key.items():
        if fr["party"] is None or fr["signed_score"] is None:
            continue
        base_key = (theme, fr["party"])
        if base_key not in baseline:
            continue
        member_defections = tuple(defections.get((bioguide, theme), ()))
        if fr["n_contested"] < cfg.min_eligible_for_display:
            continue
        if len(member_defections) < cfg.min_defection_votes:
            continue
        base = baseline[base_key]
        results.append(
            MemberThemeDeviation(
                bioguide_id=bioguide,
                full_name=fr["full_name"],
                party=fr["party"],
                chamber=fr["chamber"],
                district_number=fr["district_number"],
                impact_tag=theme,
                signed_score=fr["signed_score"],
                party_baseline=round(base, 4),
                deviation=round(fr["signed_score"] - base, 4),
                n_contested=fr["n_contested"],
                absence_rate=fr["absence_rate"],
                defection_votes=member_defections,
            )
        )

    theme_peak: dict[str, float] = {}
    for r in results:
        theme_peak[r.impact_tag] = max(theme_peak.get(r.impact_tag, 0.0), abs(r.deviation))
    results.sort(key=lambda r: (-theme_peak[r.impact_tag], r.impact_tag, -abs(r.deviation)))
    return results


def compute_party_deviations(
    conn: duckdb.DuckDBPyConnection,
    config: ScoringConfig | None = None,
    *,
    map_version: str = "2021",
    votes_path: Path | None = None,
) -> list[MemberThemeDeviation]:
    """Per theme: caucus baseline, member deviation, and the defection roll calls.

    Reported member-themes clear both gates: n_contested >= min_eligible_for_display
    AND at least min_defection_votes defection votes exist. Sorted by |deviation|
    descending within theme (themes ordered by their peak deviation).
    """
    require_map_version(map_version)
    cfg = config or load_scoring_config()
    if votes_path is not None:
        from vact.analysis.votes import validate_votes_csv

        vote_rows = validate_votes_csv(votes_path)
        return compute_party_deviations_from_votes(vote_rows, cfg, map_version=map_version)

    frame = build_scores_frame(conn, cfg, map_version=map_version)
    detail = _vote_level_rows(conn, cfg, map_version=map_version)
    return _deviations_from_frame_and_detail(frame, detail, cfg)


def compute_party_deviations_from_votes(
    vote_rows: list[Any],
    config: ScoringConfig | None = None,
    *,
    map_version: str = "2021",
) -> list[MemberThemeDeviation]:
    require_map_version(map_version)
    cfg = config or load_scoring_config()
    frame = frame_from_vote_rows(vote_rows, cfg, map_version=map_version)
    detail = detail_from_vote_rows(vote_rows)
    return _deviations_from_frame_and_detail(frame, detail, cfg)


def _fmt(x: float) -> str:
    return f"{x:+.2f}"


def render_deviations_md(
    deviations: list[MemberThemeDeviation], config: ScoringConfig
) -> str:
    generated = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    lines = [
        "# Caucus crossover votes",
        "",
        f"Axis: **{config.axis_name}** — {config.axis_description}",
        "",
        "A member appears when their caucus deviation is backed by at least "
        f"{config.min_defection_votes} crossover vote(s) (a roll call where their "
        "axis-direction opposed their party's majority) and they have "
        f"≥ {config.min_eligible_for_display} contested votes in the theme. Baseline = "
        f"{config.deviation_baseline} of the caucus. Absences are never counted as crossovers.",
        "",
    ]
    if not deviations:
        lines += ["_No qualifying caucus crossover votes._", ""]
        return "\n".join(lines)

    current_theme: str | None = None
    for r in deviations:
        if r.impact_tag != current_theme:
            lines += ["", f"## {r.impact_tag}", ""]
            current_theme = r.impact_tag
        district = f"VA-{r.district_number}" if r.district_number else r.chamber
        lines += [
            f"### {r.full_name} ({r.party}, {district}) — deviation {_fmt(r.deviation)}",
            "",
            f"- signed score {_fmt(r.signed_score)} vs caucus baseline "
            f"{_fmt(r.party_baseline)}  (n={r.n_contested}"
            + (f", absence rate {r.absence_rate:.0%}" if r.absence_rate else "")
            + ")",
            f"- {len(r.defection_votes)} crossover vote(s) — voted against the caucus majority on:",
        ]
        for d in r.defection_votes:
            summary = (d.plain_language_summary or "").strip() or "_(no adjudicated summary)_"
            link = f"[{d.bill_id or d.vote_id}]({d.source_link})" if d.source_link else (
                d.bill_id or d.vote_id
            )
            lines.append(
                f"  - {d.vote_date} · {link} · voted **{d.position}** — {summary}"
            )
        lines.append("")
    return "\n".join(lines)


def write_deviations_report(
    *,
    map_version: str = "2021",
    warehouse_path: Path | None = None,
    config_path: Path | None = None,
    out_path: Path | None = None,
    votes_path: Path | None = None,
) -> Path:
    conn = connect(warehouse_path)
    try:
        ensure_schema(conn)
        cfg = load_scoring_config(config_path)
        deviations = compute_party_deviations(
            conn, cfg, map_version=map_version, votes_path=votes_path
        )
    finally:
        conn.close()
    dest = out_path or (REPORTS_DIR / "party_deviations.md")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(render_deviations_md(deviations, cfg), encoding="utf-8")
    return dest
