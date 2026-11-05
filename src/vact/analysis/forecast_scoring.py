"""Score published forecasts against certified returns.

The published forecast is the artifact the public actually saw: `web/data/seats.json`
and `web/data/senate.json` at the final deploy. `data/predictions_seats.csv` is not
used, because it stopped being written at seat-v1.0 in August and never carried the
numbers that shipped.

Nothing here is persisted (AGENTS.md section 8). The report is recomputed from
`data/election_results_2026.csv` plus those payloads every time it is rendered, so a
later canvass correction changes the score rather than contradicting a stored one.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from vact.paths import DATA_DIR, REPO_ROOT

RESULTS_PATH = DATA_DIR / "election_results_2026.csv"
SEATS_PATH = REPO_ROOT / "web" / "data" / "seats.json"
SENATE_PATH = REPO_ROOT / "web" / "data" / "senate.json"
RACES_PATH = REPO_ROOT / "web" / "data" / "races.json"

# A race is "competitive" when the forecast actually took a position worth scoring.
# Outside this band the call is arithmetic, not judgement, and including those races
# flatters every aggregate: the safe seats alone score a Brier of 0.0004.
COMPETITIVE_LO = 0.05
COMPETITIVE_HI = 0.95


def load_results(path: Path | None = None) -> dict[str, dict[str, Any]]:
    dest = path or RESULTS_PATH
    out: dict[str, dict[str, Any]] = {}
    with dest.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            dem, rep = float(row["dem_votes"]), float(row["rep_votes"])
            if dem + rep <= 0:
                continue
            out[row["race_id"]] = {
                "dem_votes": dem,
                "rep_votes": rep,
                "dem_two_party": dem / (dem + rep),
                "dem_won": dem > rep,
                "complete": row["localities_reporting"] == row["localities_total"],
                "status": row.get("status", ""),
            }
    return out


def load_published(paths: tuple[Path, Path] | None = None) -> dict[str, dict[str, Any]]:
    seats_path, senate_path = paths or (SEATS_PATH, SENATE_PATH)
    out: dict[str, dict[str, Any]] = {}
    for path in (seats_path, senate_path):
        for race in json.loads(path.read_text(encoding="utf-8"))["races"]:
            out[race["race_id"]] = {
                "prob_dem": float(race["prob_dem"]),
                "mu_dem_two_party": float(race["mu_dem_two_party"]),
                "model_version": race["model_version"],
            }
    return out


def _incumbent_party() -> dict[str, str]:
    races = json.loads(RACES_PATH.read_text(encoding="utf-8"))["races"]
    return {r["race_id"]: r["incumbent"]["party"] for r in races}


def _pres_lean() -> dict[str, float]:
    races = json.loads(RACES_PATH.read_text(encoding="utf-8"))["races"]
    out = {}
    for r in races:
        lean = (r.get("district_lean") or {}).get("pres_2024_two_party_dem_share")
        if lean is not None:
            out[r["race_id"]] = float(lean)
    return out


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"n": 0}
    n = len(rows)
    return {
        "n": n,
        "brier": sum(r["brier"] for r in rows) / n,
        "winners_called": sum(1 for r in rows if r["called"]),
        "share_mae_pp": sum(abs(r["share_error"]) for r in rows) / n * 100,
        "share_bias_pp": sum(r["share_error"] for r in rows) / n * 100,
    }


def score(
    *,
    results_path: Path | None = None,
    published_paths: tuple[Path, Path] | None = None,
) -> dict[str, Any]:
    """Per-race and aggregate scoring, plus the two baselines worth beating."""
    results = load_results(results_path)
    published = load_published(published_paths)
    incumbents = _incumbent_party()
    leans = _pres_lean()

    rows: list[dict[str, Any]] = []
    for race_id, actual in sorted(results.items()):
        fc = published.get(race_id)
        if fc is None:
            continue
        p = fc["prob_dem"]
        won = 1 if actual["dem_won"] else 0
        rows.append({
            "race_id": race_id,
            "prob_dem": p,
            "mu_dem_two_party": fc["mu_dem_two_party"],
            "actual_dem_two_party": actual["dem_two_party"],
            "share_error": fc["mu_dem_two_party"] - actual["dem_two_party"],
            "brier": (p - won) ** 2,
            "called": (p >= 0.5) == bool(won),
            "dem_won": bool(won),
            "complete": actual["complete"],
            "model_version": fc["model_version"],
        })

    competitive = [r for r in rows if COMPETITIVE_LO < r["prob_dem"] < COMPETITIVE_HI]
    safe = [r for r in rows if r not in competitive]

    inc_brier = []
    lean_abs = []
    for r in rows:
        won = 1 if r["dem_won"] else 0
        inc_p = 1.0 if incumbents.get(r["race_id"]) == "Democrat" else 0.0
        inc_brier.append((inc_p - won) ** 2)
        lean = leans.get(r["race_id"])
        if lean is not None:
            lean_abs.append(abs(lean - r["actual_dem_two_party"]))

    return {
        "races": rows,
        "all": _aggregate(rows),
        "competitive": _aggregate(competitive),
        "safe": _aggregate(safe),
        "baselines": {
            "always_incumbent_brier": (sum(inc_brier) / len(inc_brier)) if inc_brier else None,
            "coin_flip_brier": 0.25,
            "pres_lean_share_mae_pp": (sum(lean_abs) / len(lean_abs) * 100) if lean_abs else None,
        },
        "incomplete_races": [r["race_id"] for r in rows if not r["complete"]],
    }
