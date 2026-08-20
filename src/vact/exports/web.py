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

from vact.analysis.deviations import compute_party_deviations
from vact.analysis.estimators import attach_empirical_bayes
from vact.analysis.scoring import build_scores_frame, load_scoring_config
from vact.analysis.votes import resolve_votes_path
from vact.exports.data import list_delegation
from vact.paths import REPO_ROOT
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
    return {
        "meta": {
            "generated_at_utc": _generated_at(),
            "map_version": map_version,
            "axis": {"name": config.axis_name, "description": config.axis_description},
            "themes": themes,
            "sufficient_min": config.min_contested,
            "estimate_default": "eb",
            "baselines": baselines,
        },
        "scores": scores,
        "deviations": devs,
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
    written: list[Path] = []
    for name in ("meta", "scores", "deviations", "delegation"):
        path = dest / f"{name}.json"
        path.write_text(json.dumps(payload[name], indent=2, ensure_ascii=False), encoding="utf-8")
        written.append(path)
    return written
