"""Challenger historical House voting (Prompt 11).

Extracts roll calls for challengers with prior federal service, emits a
roll-call review queue with RULE-suggested themes, and member-level
`data/votes_historical_candidates.csv` rows for the full Democratic caucus on
those roll calls (for era-appropriate EB priors). Does not auto-adjudicate.
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Any, Sequence

import duckdb
import yaml

from vact.analysis.races import RaceRegistry, load_races
from vact.analysis.scoring import ScoringConfig, load_scoring_config
from vact.analysis.votes import CSV_COLUMNS, VoteRow
from vact.analysis.estimators import attach_empirical_bayes_by_era
from vact.models.legislators import LegislatorRecord
from vact.paths import REPO_ROOT
from vact.sources import legislators as legislator_source
from vact.transforms.classify import load_rulebook, tags_for_corpus
from vact.warehouse.connection import ensure_schema

CONGRESS_TERMS_PATH = REPO_ROOT / "config" / "congress_terms.yaml"
HISTORICAL_CANDIDATES_PATH = REPO_ROOT / "data" / "votes_historical_candidates.csv"
HISTORICAL_REVIEW_PATH = REPO_ROOT / "data" / "historical_rollcall_review.csv"

ERA_CAPTION = (
    "Scored on votes from the {eras} Congress; themes matched by adjudication, "
    "not identical bills. Cross-era comparison is indicative, not exact."
)

HISTORICAL_COLUMNS: tuple[str, ...] = CSV_COLUMNS + ("congress_era",)

REVIEW_COLUMNS: tuple[str, ...] = (
    "vote_id",
    "congress_era",
    "vote_date",
    "vote_category",
    "bill_id",
    "title",
    "plain_language_summary",
    "crs_url",
    "suggested_theme",
    "suggested",
    "adjudicated",
    "notes",
)


class HistoricalError(ValueError):
    pass


def load_congress_terms(path: Path | None = None) -> dict[int, dict[str, str]]:
    dest = path or CONGRESS_TERMS_PATH
    payload = yaml.safe_load(dest.read_text(encoding="utf-8")) or {}
    raw = payload.get("terms") or {}
    out: dict[int, dict[str, str]] = {}
    for key, meta in raw.items():
        out[int(key)] = {
            "start": str(meta["start"]),
            "end": str(meta["end"]),
            "label": str(meta.get("label") or f"{key}th Congress"),
        }
    return out


def challenger_targets(registry: RaceRegistry | None = None) -> list[dict[str, Any]]:
    """Challengers with House prior federal service and bioguide ids."""
    reg = registry or load_races()
    targets: list[dict[str, Any]] = []
    for race in reg.races:
        ch = race.challenger
        if not ch.prior_federal_service:
            continue
        for svc in ch.prior_federal_service:
            if svc.chamber != "House":
                continue
            targets.append(
                {
                    "race_id": race.race_id,
                    "district": race.district,
                    "name": ch.name,
                    "party": ch.party,
                    "bioguide_id": svc.bioguide_id,
                    "congresses": list(svc.congresses),
                }
            )
    return targets


def _load_legislators() -> list[LegislatorRecord]:
    try:
        paths = legislator_source.fetch_all()
    except Exception:
        return []
    return legislator_source.parse_legislators(
        paths["legislators-current"]
    ) + legislator_source.parse_legislators(paths["legislators-historical"])


def party_at(
    records: Sequence[LegislatorRecord],
    bioguide_id: str,
    vote_date: date,
    *,
    chamber: str = "House",
) -> str | None:
    want = "rep" if chamber == "House" else "sen"
    for rec in records:
        if rec.id.bioguide != bioguide_id:
            continue
        for term in rec.terms:
            if term.type != want:
                continue
            if term.start <= vote_date < term.end:
                party = (term.party or "").strip()
                if not party:
                    return None
                if party.lower().startswith("dem"):
                    return "Democrat"
                if party.lower().startswith("rep"):
                    return "Republican"
                return party
    return None


def _member_name(records: Sequence[LegislatorRecord], bioguide_id: str) -> str:
    for rec in records:
        if rec.id.bioguide == bioguide_id:
            return rec.name.official_full or f"{rec.name.first or ''} {rec.name.last or ''}".strip()
    return bioguide_id


def seed_rollcall_ids(
    conn: duckdb.DuckDBPyConnection,
    targets: Sequence[dict[str, Any]],
) -> set[str]:
    """Roll calls where any target challenger cast a vote."""
    bios = {t["bioguide_id"] for t in targets}
    congresses = {c for t in targets for c in t["congresses"]}
    if not bios:
        return set()
    bio_ph = ", ".join("?" for _ in bios)
    cong_ph = ", ".join("?" for _ in congresses)
    rows = conn.execute(
        f"""
        SELECT DISTINCT v.vote_id
        FROM fact_vote v
        JOIN fact_member_vote mv ON mv.vote_id = v.vote_id
        WHERE mv.bioguide_id IN ({bio_ph})
          AND v.congress IN ({cong_ph})
          AND v.chamber = 'House'
        """,
        [*bios, *sorted(congresses)],
    ).fetchall()
    return {r[0] for r in rows}


def build_review_queue_rows(
    conn: duckdb.DuckDBPyConnection,
    *,
    vote_ids: set[str] | None = None,
    targets: Sequence[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    targets = list(targets or challenger_targets())
    ids = vote_ids if vote_ids is not None else seed_rollcall_ids(conn, targets)
    if not ids:
        return []
    rb = load_rulebook()
    id_ph = ", ".join("?" for _ in ids)
    raw = conn.execute(
        f"""
        SELECT
            v.vote_id,
            CAST(v.congress AS VARCHAR) AS congress_era,
            CAST(v.vote_date AS VARCHAR) AS vote_date,
            v.vote_category,
            coalesce(v.bill_id, '') AS bill_id,
            coalesce(b.title, '') AS title,
            coalesce(b.short_title, '') AS short_title,
            coalesce(b.plain_language_summary, '') AS plain_language_summary,
            '' AS crs_url,
            coalesce(v.source_url, '') AS source_url,
            coalesce(b.policy_area, '') AS policy_area
        FROM fact_vote v
        LEFT JOIN dim_bill b ON b.bill_id = v.bill_id
        WHERE v.vote_id IN ({id_ph})
        ORDER BY v.vote_date, v.vote_id
        """,
        sorted(ids),
    ).fetchall()
    cols = [
        "vote_id",
        "congress_era",
        "vote_date",
        "vote_category",
        "bill_id",
        "title",
        "short_title",
        "plain_language_summary",
        "crs_url",
        "source_url",
        "policy_area",
    ]
    out: list[dict[str, str]] = []
    for rec in raw:
        row = dict(zip(cols, rec, strict=True))
        tags = tags_for_corpus(
            title=row["title"] or row["short_title"],
            short_title=row["short_title"],
            policy_area=row["policy_area"] or None,
            rulebook=rb,
        )
        suggested = tags[0] if tags else ""
        out.append(
            {
                "vote_id": row["vote_id"],
                "congress_era": row["congress_era"],
                "vote_date": row["vote_date"][:10],
                "vote_category": row["vote_category"],
                "bill_id": row["bill_id"],
                "title": row["title"] or row["short_title"],
                "plain_language_summary": row["plain_language_summary"],
                "crs_url": row["crs_url"],
                "suggested_theme": suggested,
                "suggested": "true",
                "adjudicated": "false",
                "notes": "",
            }
        )
    return out


def _adjudicated_themes(review: Sequence[dict[str, str]]) -> dict[str, set[str]]:
    """vote_id -> themes confirmed by operator (adjudicated=true, theme set)."""
    out: dict[str, set[str]] = {}
    for row in review:
        if str(row.get("adjudicated", "")).lower() not in {"true", "1", "yes"}:
            continue
        theme = (row.get("suggested_theme") or row.get("theme") or "").strip()
        if not theme:
            continue
        out.setdefault(row["vote_id"], set()).add(theme)
    return out


def build_historical_candidate_rows(
    conn: duckdb.DuckDBPyConnection,
    *,
    vote_ids: set[str] | None = None,
    review_rows: Sequence[dict[str, str]] | None = None,
    legislators: Sequence[LegislatorRecord] | None = None,
    config: ScoringConfig | None = None,
) -> list[dict[str, str]]:
    """Democratic caucus member rows for adjudicated historical roll calls."""
    cfg = config or load_scoring_config()
    legs = list(legislators) if legislators is not None else _load_legislators()
    review = list(review_rows) if review_rows is not None else load_review_queue()
    ids = vote_ids if vote_ids is not None else {r["vote_id"] for r in review}
    if not ids:
        return []
    id_ph = ", ".join("?" for _ in ids)
    cat_ph = ", ".join("?" for _ in sorted(cfg.include_categories))
    votes = conn.execute(
        f"""
        SELECT
            v.vote_id,
            v.congress,
            CAST(v.vote_date AS VARCHAR) AS vote_date,
            v.vote_category,
            coalesce(v.bill_id, '') AS bill_id,
            coalesce(v.source_url, '') AS source_url,
            coalesce(b.plain_language_summary, '') AS plain_language_summary,
            mv.bioguide_id,
            mv.position
        FROM fact_vote v
        JOIN fact_member_vote mv ON mv.vote_id = v.vote_id
        LEFT JOIN dim_bill b ON b.bill_id = v.bill_id
        WHERE v.vote_id IN ({id_ph})
          AND v.vote_category IN ({cat_ph})
          AND mv.position IN ('YEA', 'NAY', 'PRESENT', 'NOT_VOTING')
        ORDER BY v.vote_date, v.vote_id, mv.bioguide_id
        """,
        [*sorted(ids), *sorted(cfg.include_categories)],
    ).fetchall()
    themes_by_vote = _adjudicated_themes(review)
    rows: list[dict[str, str]] = []
    for vote_id, congress, vote_date, _category, bill_id, source_url, summary, bio, position in votes:
        vdate = date.fromisoformat(vote_date[:10])
        party = party_at(legs, bio, vdate)
        if party != "Democrat":
            continue
        themes = themes_by_vote.get(vote_id)
        if not themes:
            continue
        cast = position.lower()
        contested = position in ("YEA", "NAY")
        for theme in sorted(themes):
            rows.append(
                {
                    "member_bioguide_id": bio,
                    "member_name": _member_name(legs, bio),
                    "district": "",
                    "party": party,
                    "congress": str(congress),
                    "chamber": "House",
                    "rollcall_id": vote_id,
                    "rollcall_date": vote_date[:10],
                    "bill_id": bill_id,
                    "theme": theme,
                    "axis_direction": "",
                    "vote_cast": cast,
                    "contested": "true" if contested else "false",
                    "adjudication_note": "",
                    "adjudicator": "",
                    "adjudication_date": "",
                    "source_url": source_url,
                    "plain_language_summary": summary,
                    "coded_blind": "false",
                    "congress_era": str(congress),
                }
            )
    return rows


def load_historical_candidates_raw(path: Path | None = None) -> list[dict[str, str]]:
    dest = path or HISTORICAL_CANDIDATES_PATH
    if not dest.is_file():
        return []
    with dest.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def load_historical_candidates(path: Path | None = None) -> list[VoteRow]:
    out: list[VoteRow] = []
    for rec in load_historical_candidates_raw(path):
        if not (rec.get("axis_direction") or "").strip():
            continue
        if rec.get("adjudicator") not in {"HUMAN", "RULE", "LLM"}:
            continue
        payload = dict(rec)
        if not payload.get("coded_blind"):
            payload["coded_blind"] = "false"
        if "congress_era" not in payload:
            payload["congress_era"] = ""
        out.append(VoteRow.model_validate(payload))
    return out


def write_historical_candidates(rows: Sequence[dict[str, Any]], path: Path | None = None) -> Path:
    dest = path or HISTORICAL_CANDIDATES_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(
        rows,
        key=lambda r: (
            r.get("congress_era", ""),
            r.get("theme", ""),
            r.get("rollcall_date", ""),
            r.get("rollcall_id", ""),
            r.get("member_bioguide_id", ""),
        ),
    )
    with dest.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(HISTORICAL_COLUMNS), lineterminator="\n")
        writer.writeheader()
        for row in ordered:
            writer.writerow({col: row.get(col, "") for col in HISTORICAL_COLUMNS})
    return dest


def load_review_queue(path: Path | None = None) -> list[dict[str, str]]:
    dest = path or HISTORICAL_REVIEW_PATH
    if not dest.is_file():
        return []
    with dest.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def write_review_queue(rows: Sequence[dict[str, str]], path: Path | None = None) -> Path:
    dest = path or HISTORICAL_REVIEW_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(REVIEW_COLUMNS), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return dest


def merge_review_queue(
    proposed: Sequence[dict[str, str]],
    existing: Sequence[dict[str, str]],
) -> list[dict[str, str]]:
    """Preserve operator adjudication; append new roll calls."""
    by_id = {r["vote_id"]: dict(r) for r in existing}
    for row in proposed:
        vid = row["vote_id"]
        if vid not in by_id:
            by_id[vid] = dict(row)
    return sorted(by_id.values(), key=lambda r: (r["vote_date"], r["vote_id"]))


def adjudicated_historical_rows(rows: Sequence[VoteRow] | None = None) -> list[VoteRow]:
    if rows is None:
        return load_historical_candidates()
    out: list[VoteRow] = []
    for row in rows:
        if row.adjudicator not in {"HUMAN", "RULE", "LLM"}:
            continue
        try:
            _ = row.axis_direction
            out.append(row)
        except Exception:
            continue
    return out


def frame_from_historical_votes(
    rows: Sequence[VoteRow] | None = None,
    config: ScoringConfig | None = None,
    *,
    map_version: str = "2021",
) -> list[dict[str, Any]]:
    from vact.analysis.scoring import frame_from_vote_rows

    adjudicated = adjudicated_historical_rows(list(rows) if rows is not None else None)
    if not adjudicated:
        return []
    return frame_from_vote_rows(adjudicated, config, map_version=map_version)


def era_caption(congresses: Sequence[int], terms: dict[int, dict[str, str]] | None = None) -> str:
    tmap = terms or load_congress_terms()
    labels: list[str] = []
    for c in sorted(set(congresses)):
        meta = tmap.get(c)
        if meta:
            labels.append(meta["label"].replace(" Congress", ""))
        else:
            labels.append(str(c))
    if len(labels) == 1:
        eras = labels[0]
    elif len(labels) == 2:
        eras = f"{labels[0]}–{labels[1]}"
    else:
        eras = ", ".join(labels[:-1]) + f", and {labels[-1]}"
    return ERA_CAPTION.format(eras=eras)


def build_head_to_head_payload(
    incumbent_scores: Sequence[dict[str, Any]],
    *,
    config: ScoringConfig | None = None,
    registry: RaceRegistry | None = None,
    historical_path: Path | None = None,
) -> dict[str, Any]:
    cfg = config or load_scoring_config()
    reg = registry or load_races()
    hist_adjudicated = adjudicated_historical_rows()
    caucus_frame = frame_from_historical_votes(hist_adjudicated, cfg)
    caucus_scored, _ = (
        attach_empirical_bayes_by_era(caucus_frame, cfg) if caucus_frame else ([], [])
    )

    def _challenger_row(bio: str, theme: str) -> dict[str, Any] | None:
        matches = [
            r for r in caucus_scored if r["bioguide_id"] == bio and r["impact_tag"] == theme
        ]
        if not matches:
            return None
        return max(matches, key=lambda r: int(r.get("n_contested") or 0))

    inc_by_bio: dict[str, list[dict[str, Any]]] = {}
    for row in incumbent_scores:
        inc_by_bio.setdefault(row["bioguide_id"], []).append(row)

    def _incumbent_themes(bio: str | None) -> list[dict[str, Any]]:
        if not bio:
            return []
        inc_rows = {r["theme"]: r for r in inc_by_bio.get(bio, [])}
        return [
            {
                "theme": theme,
                "incumbent": _score_slice(inc_rows[theme], historical=False),
                "challenger": None,
            }
            for theme in sorted(inc_rows)
        ]

    races_out: dict[str, Any] = {}
    for race in reg.races:
        rid = race.race_id
        inc_bio = race.incumbent.bioguide_id
        if not race.challenger.prior_federal_service:
            themes = _incumbent_themes(inc_bio)
            races_out[rid] = {
                "status": "incumbent_only" if themes else "no_federal_record",
                "era_caption": None,
                "themes": themes,
                "incumbent_only": True,
            }
            continue
        svc = next(
            (s for s in race.challenger.prior_federal_service if s.chamber == "House"),
            None,
        )
        if svc is None:
            themes = _incumbent_themes(inc_bio)
            races_out[rid] = {
                "status": "incumbent_only" if themes else "no_federal_record",
                "era_caption": None,
                "themes": themes,
                "incumbent_only": True,
            }
            continue
        ch_bio = svc.bioguide_id
        caption = era_caption(svc.congresses)
        inc_rows = {r["theme"]: r for r in inc_by_bio.get(inc_bio or "", []) if inc_bio}
        ch_rows = {t: _challenger_row(ch_bio, t) for t in inc_rows}
        themes = []
        for theme in sorted(inc_rows):
            inc = inc_rows[theme]
            ch = ch_rows.get(theme)
            themes.append(
                {
                    "theme": theme,
                    "incumbent": _score_slice(inc, historical=False),
                    "challenger": _score_slice(ch, historical=True) if ch else None,
                }
            )
        races_out[rid] = {
            "status": "ready" if any(ch_rows.get(t) for t in inc_rows) else "pending_adjudication",
            "era_caption": caption,
            "congress_eras": [str(c) for c in svc.congresses],
            "themes": themes,
            "incumbent_only": False,
        }
    return {"races": races_out}


def _score_slice(row: dict[str, Any] | None, *, historical: bool) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "bioguide_id": row.get("bioguide_id"),
        "full_name": row.get("full_name"),
        "party": row.get("party"),
        "eb_score": row.get("eb_score"),
        "cred_lo": row.get("cred_lo"),
        "cred_hi": row.get("cred_hi"),
        "n_contested": row.get("n_contested") or row.get("n"),
        "sufficient": row.get("sufficient"),
        "historical": historical,
        "congress_era": row.get("congress_era"),
    }


def propose_historical_artifacts(
    conn: duckdb.DuckDBPyConnection,
    *,
    config: ScoringConfig | None = None,
) -> tuple[Path, Path, dict[str, int]]:
    ensure_schema(conn)
    targets = challenger_targets()
    ids = seed_rollcall_ids(conn, targets)
    proposed_review = build_review_queue_rows(conn, vote_ids=ids, targets=targets)
    merged_review = merge_review_queue(proposed_review, load_review_queue())
    review_path = write_review_queue(merged_review)
    candidate_rows = build_historical_candidate_rows(conn, vote_ids=ids, review_rows=merged_review)
    prior_candidates = load_historical_candidates_raw()
    by_key = {
        (r["member_bioguide_id"], r["rollcall_id"], r["theme"]): r for r in prior_candidates
    }
    for row in candidate_rows:
        key = (row["member_bioguide_id"], row["rollcall_id"], row["theme"])
        if key not in by_key:
            by_key[key] = row
    candidates_path = write_historical_candidates(list(by_key.values()))
    stats = {
        "seed_rollcalls": len(ids),
        "review_rows": len(merged_review),
        "candidate_rows": len(by_key),
        "targets": len(targets),
    }
    return review_path, candidates_path, stats
