"""Export the analysis layer to static JSON for the Next.js dashboard (Vercel).

The Python pipeline stays the source of truth; this serializes the already-computed
signed scoring frame, within-party deviations, and delegation into small JSON files
that the web app imports at build time. No metric is persisted in the warehouse — it
is all recomputed live here at export time (AGENTS.md §8).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from vact.analysis.deviations import compute_party_deviations
from vact.analysis.estimators import attach_empirical_bayes
from vact.analysis.excluded_votes import export_excluded_votes
from vact.analysis.methodology import build_methodology_payload
from vact.analysis.scoring import build_scores_frame, load_scoring_config
from vact.analysis.symmetry_audit import build_symmetry_audit
from vact.analysis.challenger_historical import build_head_to_head_payload
from vact.exports.brand import build_about_payload, build_brand_payload
from vact.exports.disclosure import build_disclosure_payload
from vact.analysis.timeseries import expanding_series
from vact.analysis.cosponsorship import score_cosponsorship, serialize_cosponsor_rows
from vact.analysis.poll_average import build_generic_ballot
from vact.analysis.races import races_for_web
from vact.analysis.seat_model import predict_races
from vact.analysis.senate_model import predict as predict_senate
from vact.pipeline.cosponsorship import load_cosp_config
from vact.pipeline.fec import latest_snapshot
from vact.analysis.votes import resolve_votes_path, validate_votes_csv, vote_rows_from_warehouse
from vact.exports.data import list_delegation
from vact.paths import REPO_ROOT

logger = structlog.get_logger(__name__)
from vact.warehouse.connection import connect, ensure_schema

# Default target: the Next.js app reads these via `import ... from "@/data/*.json"`.
WEB_DATA_DIR = REPO_ROOT / "web" / "data"


def _generated_at() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_web_payload(
    conn,
    config,
    *,
    map_version: str = "2021",
    votes_path: Path | None = None,
) -> dict[str, Any]:
    frame = build_scores_frame(conn, config, map_version=map_version, votes_path=votes_path)
    frame, baselines = attach_empirical_bayes(frame, config)
    deviations = compute_party_deviations(
        conn, config, map_version=map_version, votes_path=votes_path
    )
    delegation = list_delegation(conn, map_version=map_version)

    scores = [
        {
            "bioguide_id": r["bioguide_id"],
            "full_name": r["full_name"],
            "party": r["party"],
            "chamber": r["chamber"],
            "district_number": r["district_number"],
            "theme": r["impact_tag"],
            "signed_score": r["signed_score"],
            "wilson_low": r["wilson_low"],
            "wilson_high": r["wilson_high"],
            "raw_score": r["raw_score"],
            "wilson_lo": r["wilson_lo"],
            "wilson_hi": r["wilson_hi"],
            "eb_score": r["eb_score"],
            "cred_lo": r["cred_lo"],
            "cred_hi": r["cred_hi"],
            "n": r["n"],
            "k": r["k"],
            "n_contested": r["n_contested"],
            "n_yea": r["n_yea"],
            "n_nay": r["n_nay"],
            "n_pro": r["n_pro"],
            "absence_rate": r["absence_rate"],
            "sufficient": r["sufficient"],
            "prior_alpha": r["prior_alpha"],
            "prior_beta": r["prior_beta"],
            "prior_source": r["prior_source"],
            "prior_only": r["prior_only"],
        }
        for r in frame
        if r["eb_score"] is not None
    ]

    devs = [
        {
            "bioguide_id": d.bioguide_id,
            "full_name": d.full_name,
            "party": d.party,
            "district_number": d.district_number,
            "theme": d.impact_tag,
            "signed_score": d.signed_score,
            "party_baseline": d.party_baseline,
            "deviation": d.deviation,
            "n_contested": d.n_contested,
            "defection_votes": [
                {
                    "vote_id": v.vote_id,
                    "vote_date": v.vote_date,
                    "bill_id": v.bill_id,
                    "summary": v.plain_language_summary,
                    "position": v.position,
                    "source_link": v.source_link,
                }
                for v in d.defection_votes
            ],
        }
        for d in deviations
    ]

    themes = sorted({s["theme"] for s in scores})
    if votes_path is not None:
        vote_rows = validate_votes_csv(votes_path)
    else:
        vote_rows = vote_rows_from_warehouse(conn, config, map_version=map_version)
    export_excluded_votes(conn, config=config)
    symmetry = build_symmetry_audit(vote_rows, scores)
    methodology = build_methodology_payload(
        config, scores, baselines, symmetry_audit=symmetry
    )
    timeseries = expanding_series(vote_rows, config)
    cosp_cfg = load_cosp_config()
    cosp_frame = score_cosponsorship(extra_members=cosp_cfg.get("extra_members") or [], config=config)
    races = races_for_web()
    fec_latest = latest_snapshot()
    fec_payload: dict[str, Any] = {"latest_path": None, "snapshot": None}
    if fec_latest is not None and fec_latest.is_file():
        fec_payload = {
            "latest_path": str(fec_latest.relative_to(REPO_ROOT)),
            "snapshot": json.loads(fec_latest.read_text(encoding="utf-8")),
        }
    return {
        "meta": {
            "generated_at_utc": _generated_at(),
            "map_version": map_version,
            "axis": {"name": config.axis_name, "description": config.axis_description},
            "themes": themes,
            "sufficient_min": config.min_contested,
            "estimate_default": "eb",
            "baselines": baselines,
            "election_date": races["election_date"],
            "days_until_election": races["days_until_election"],
            "races_as_of": races["as_of"],
        },
        "scores": scores,
        "deviations": devs,
        "methodology": methodology,
        "timeseries": timeseries,
        "cosponsorship": {
            "never_blended": True,
            "rows": serialize_cosponsor_rows(cosp_frame),
        },
        "races": races,
        "fec": fec_payload,
        "seats": predict_races(),
        "senate": predict_senate(),
        "generic_ballot": build_generic_ballot(),
        "disclosure": build_disclosure_payload(),
        "brand": build_brand_payload(),
        "about": build_about_payload(),
        "head_to_head": build_head_to_head_payload(scores),
        "delegation": [
            {
                "bioguide_id": m["bioguide_id"],
                "full_name": m["full_name"],
                "party": m["party"],
                "chamber": m["chamber"],
                "district_number": m["district_number"],
                "partisan_lean": m.get("partisan_lean"),
                "is_target": m.get("is_target"),
            }
            for m in delegation
        ],
    }


def export_web(
    *,
    map_version: str = "2021",
    out_dir: Path | None = None,
    warehouse_path: Path | None = None,
    config_path: Path | None = None,
    votes_path: Path | None = None,
    from_warehouse: bool = False,
) -> list[Path]:
    """Write scores/deviations/delegation/meta JSON for the web app. Returns paths.

    Scores and deviations read `data/votes.csv` when present (Prompt 1). Delegation
    still comes from the warehouse (not vote grain). Pass `from_warehouse=True` to
    force the DuckDB SQL path (bootstrap / identity check).
    """
    csv_path = None if from_warehouse else resolve_votes_path(votes_path)
    conn = connect(warehouse_path)
    try:
        ensure_schema(conn)
        cfg = load_scoring_config(config_path)
        payload = build_web_payload(conn, cfg, map_version=map_version, votes_path=csv_path)
    finally:
        conn.close()

    dest = out_dir or WEB_DATA_DIR
    dest.mkdir(parents=True, exist_ok=True)

    # Publication debt, reported on every build. docs/ and briefs already refuse
    # scored rows with no plain-language summary; web/ only enforces it when
    # require_plain_language_summary is on. Keeping the count visible stops the
    # gap between the published methodology and the live site going quiet.
    scores = payload.get("scores") or []
    missing = [
        s_ for s_ in scores
        if s_.get("signed_score") is not None
        and not str(s_.get("plain_language_summary") or "").strip()
    ]
    if missing:
        logger.warning(
            "web.summary_debt",
            scored_rows=len(scores),
            without_summary=len(missing),
            enforced=cfg.require_plain_language_summary,
        )
        if cfg.require_plain_language_summary:
            keep = {id(s_) for s_ in scores} - {id(s_) for s_ in missing}
            payload["scores"] = [s_ for s_ in scores if id(s_) in keep]

    written: list[Path] = []
    for name in (
        "meta",
        "scores",
        "deviations",
        "delegation",
        "methodology",
        "timeseries",
        "cosponsorship",
        "races",
        "fec",
        "seats",
        "senate",
        "generic_ballot",
        "disclosure",
        "brand",
        "about",
        "head_to_head",
    ):
        path = dest / f"{name}.json"
        path.write_text(json.dumps(payload[name], indent=2, ensure_ascii=False), encoding="utf-8")
        written.append(path)
    return written
