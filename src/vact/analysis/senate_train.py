"""Build the Senate training extract from MEDSL Senate returns + state presidential lean.

Two things make this cleaner than the House extract:

* **States are a permanent panel.** The House model drops 2012 and 2022 because
  district numbers do not survive redistricting. Every Senate cycle is usable, so
  2010–2024 gives eight cycles instead of five.
* **Lean is the real thing.** The House model trains on lagged *House* share and
  predicts from *presidential* share, a transfer SEAT_MODEL_SPEC.md flags as
  load-bearing. Here both sides are state presidential two-party share, so there
  is no transfer to assume.

Sample size is the constraint the House model does not have: roughly 33 races a
cycle, ~265 total, and races inside a cycle share the national environment. That
is why `nat_env` stays frozen rather than estimated, and why the feature set is
deliberately short.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any, Iterable

from vact.analysis.seat_model import _norm_name, prior_presidential_year
from vact.paths import REPO_ROOT

SENATE_RAW = REPO_ROOT / "data" / "raw" / "medsl" / "senate_1976_2024.tab"
HOUSE_RAW = REPO_ROOT / "data" / "raw" / "medsl" / "house_1976_2022.csv"

# National House two-party Democratic share for cycles outside the committed
# MEDSL House extract (which ends at 2022). This is the quantity the generic
# ballot forecasts, so training and production nat_env stay the same construct.
# 2024: R 74,390,864 / D 70,571,330 (Wikipedia, 2024 U.S. House elections).
NATIONAL_HOUSE_OVERRIDE = {2024: 70_571_330 / (70_571_330 + 74_390_864)}
PRES_STATE = REPO_ROOT / "data" / "raw" / "wikipedia" / "president_state_two_party.csv"
TRAIN_PATH = REPO_ROOT / "data" / "seat_model" / "senate_races_train.csv"

TRAIN_FIELDS = (
    "year", "state_po", "race_key", "dem_two_party", "dem_winner",
    "incumbent_party", "lean_rel_dem", "inc_dem", "midterm_dem", "nat_env",
    "dem_name", "rep_name",
)

STATE_PO = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA",
    "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE", "District of Columbia": "DC",
    "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL",
    "Indiana": "IN", "Iowa": "IA", "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA",
    "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI",
    "Minnesota": "MN", "Mississippi": "MS", "Missouri": "MO", "Montana": "MT",
    "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH", "New Jersey": "NJ",
    "New Mexico": "NM", "New York": "NY", "North Carolina": "NC", "North Dakota": "ND",
    "Ohio": "OH", "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA",
    "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN",
    "Texas": "TX", "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA",
    "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
}


class SenateTrainError(ValueError):
    """Raw input missing or malformed."""


def _f(value: str) -> float:
    try:
        return float(value or 0.0)
    except ValueError:
        return 0.0


def load_senate_raw(path: Path | None = None) -> list[dict[str, str]]:
    dest = path or SENATE_RAW
    if not dest.is_file():
        raise SenateTrainError(
            f"MEDSL Senate returns not found: {dest}. Download file 13887039 from "
            "Harvard Dataverse doi:10.7910/DVN/PEJ5QU."
        )
    with dest.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def _general_rows(raw: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    return [
        r for r in raw
        if (r.get("stage") or "").upper() == "GEN"
        and (r.get("mode") or "").upper() == "TOTAL"
        and (r.get("writein") or "").upper() != "TRUE"
    ]


def plurality_winners(raw: Iterable[dict[str, str]]) -> dict[tuple[int, str], set[str]]:
    """(year, state) -> normalized winners of every Senate general that year.

    A state-year can hold two contests when a special runs alongside the regular
    one, so regular and special are tallied separately and both winners are kept.
    Races the two-party frame drops are included, so an incumbent whose last
    opponent was minor-party still anchors the chain.
    """
    tally: dict[tuple[int, str, bool], dict[str, float]] = {}
    for r in _general_rows(raw):
        name = _norm_name(r.get("candidate") or "")
        if not name:
            continue
        special = str(r.get("special", "")).upper() == "TRUE"
        key = (int(r["year"]), r["state_po"], special)
        tally.setdefault(key, {})
        tally[key][name] = tally[key].get(name, 0.0) + _f(r.get("candidatevotes"))
    out: dict[tuple[int, str], set[str]] = {}
    for (year, state, _special), names in tally.items():
        if not names:
            continue
        out.setdefault((year, state), set()).add(max(names.items(), key=lambda kv: kv[1])[0])
    return out


def sitting_senators(
    winners: dict[tuple[int, str], set[str]], year: int, state: str
) -> set[str]:
    """Anyone who won a Senate election in this state in the previous six years.

    Keying strictly on year-6 misses the common cases: a senator appointed to a
    vacancy and then confirmed in a special, and states whose two classes fall
    out of the regular six-year rhythm. Any win inside one full term means the
    candidate is sitting.
    """
    out: set[str] = set()
    for back in range(1, 7):
        out |= winners.get((year - back, state), set())
    return out


def aggregate_senate_races(raw: Iterable[dict[str, str]]) -> list[dict[str, Any]]:
    """One two-party regular general election per (year, state)."""
    buckets: dict[tuple[int, str], dict[str, Any]] = {}
    for r in _general_rows(raw):
        if str(r.get("special", "")).upper() == "TRUE":
            continue
        fam = (r.get("party_simplified") or "").upper()
        if fam not in {"DEMOCRAT", "REPUBLICAN"}:
            continue
        key = (int(r["year"]), r["state_po"])
        b = buckets.setdefault(key, {
            "year": int(r["year"]), "state_po": r["state_po"],
            "dem_votes": 0.0, "rep_votes": 0.0,
            "dem_name": "", "rep_name": "", "dem_top": -1.0, "rep_top": -1.0,
        })
        votes = _f(r.get("candidatevotes"))
        name = r.get("candidate") or ""
        if fam == "DEMOCRAT":
            b["dem_votes"] += votes
            if votes > b["dem_top"]:
                b["dem_name"], b["dem_top"] = name, votes
        else:
            b["rep_votes"] += votes
            if votes > b["rep_top"]:
                b["rep_name"], b["rep_top"] = name, votes

    races = []
    for b in buckets.values():
        if b["dem_votes"] <= 0 or b["rep_votes"] <= 0:
            continue  # no two-party contest; out of the estimand, not the winner index
        two = b["dem_votes"] + b["rep_votes"]
        races.append({
            "year": b["year"], "state_po": b["state_po"],
            "race_key": f"{b['state_po']}-SEN",
            "dem_two_party": b["dem_votes"] / two,
            "dem_winner": b["dem_votes"] > b["rep_votes"],
            "dem_name": b["dem_name"], "rep_name": b["rep_name"],
        })
    return races


def load_state_presidential(path: Path | None = None) -> dict[tuple[int, str], float]:
    dest = path or PRES_STATE
    if not dest.is_file():
        raise SenateTrainError(f"state presidential lean not found: {dest}")
    out: dict[tuple[int, str], float] = {}
    with dest.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            po = STATE_PO.get(row["state"].strip())
            if not po:
                continue
            out[(int(row["year"]), po)] = float(row["dem_two_party"])
    if not out:
        raise SenateTrainError(f"{dest} produced no usable rows")
    return out


def load_national_presidential(path: Path | None = None) -> dict[int, float]:
    dest = path or PRES_STATE
    dem: dict[int, float] = {}
    rep: dict[int, float] = {}
    with dest.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            y = int(row["year"])
            dem[y] = dem.get(y, 0.0) + float(row["dem_votes"])
            rep[y] = rep.get(y, 0.0) + float(row["rep_votes"])
    return {y: dem[y] / (dem[y] + rep[y]) for y in dem if dem[y] + rep[y] > 0}


def national_house_two_party(path: Path | None = None) -> dict[int, float]:
    """Year -> national two-party Democratic share of the U.S. House vote.

    `nat_env` must mean the same thing in training and in production. In
    production it comes from the generic ballot, which forecasts exactly this
    number, so training uses it too rather than the mean of that cycle's Senate
    races (which depends on which states happen to be up).
    """
    dest = path or HOUSE_RAW
    dem: dict[int, float] = {}
    rep: dict[int, float] = {}
    if dest.is_file():
        with dest.open(encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                if (r.get("stage") or "").upper() != "GEN":
                    continue
                if (r.get("mode") or "").upper() != "TOTAL":
                    continue
                if str(r.get("writein", "")).upper() == "TRUE":
                    continue
                party = (r.get("party") or "").strip().upper()
                y = int(r["year"])
                votes = _f(r.get("candidatevotes"))
                if party == "DEMOCRAT":
                    dem[y] = dem.get(y, 0.0) + votes
                elif party == "REPUBLICAN":
                    rep[y] = rep.get(y, 0.0) + votes
    out = {y: dem[y] / (dem[y] + rep[y]) for y in dem if dem.get(y, 0) + rep.get(y, 0) > 0}
    out.update(NATIONAL_HOUSE_OVERRIDE)
    return out


def midterm_dem(year: int, president_party: str) -> int:
    if year % 4 == 0:
        return 0
    return -1 if president_party == "Democrat" else 1


def build_training_rows(
    *,
    senate_path: Path | None = None,
    pres_path: Path | None = None,
    president_party_by_cycle: dict[int, str],
    train_years: Iterable[int],
) -> list[dict[str, Any]]:
    raw = load_senate_raw(senate_path)
    races = aggregate_senate_races(raw)
    winners = plurality_winners(raw)
    pres = load_state_presidential(pres_path)
    nat = load_national_presidential(pres_path)
    want = {int(y) for y in train_years}

    rows: list[dict[str, Any]] = []
    for r in sorted(races, key=lambda x: (x["year"], x["state_po"])):
        year = r["year"]
        if year not in want:
            continue
        party = president_party_by_cycle.get(year)
        if not party:
            continue
        lean_year = prior_presidential_year(year)
        state_lean = pres.get((lean_year, r["state_po"]))
        nat_lean = nat.get(lean_year)
        if state_lean is None or nat_lean is None:
            continue
        dem_n, rep_n = _norm_name(r["dem_name"]), _norm_name(r["rep_name"])
        sitting = sitting_senators(winners, year, r["state_po"])
        incumbent_party = None
        if dem_n and dem_n in sitting:
            incumbent_party = "Democrat"
        elif rep_n and rep_n in sitting:
            incumbent_party = "Republican"
        rows.append({
            "year": year,
            "state_po": r["state_po"],
            "race_key": r["race_key"],
            "dem_two_party": round(r["dem_two_party"], 6),
            "dem_winner": r["dem_winner"],
            "incumbent_party": incumbent_party or "",
            "lean_rel_dem": round(state_lean - nat_lean, 6),
            "inc_dem": 1 if incumbent_party == "Democrat" else -1 if incumbent_party == "Republican" else 0,
            "midterm_dem": midterm_dem(year, str(party)),
            "nat_env": 0.0,  # filled from the cycle's national Senate share below
            "dem_name": r["dem_name"],
            "rep_name": r["rep_name"],
        })

    # National environment: national House two-party Democratic share, centred at
    # 0.5. Coefficient is frozen at 1.0 (it is constant within a cycle, so it is
    # not separately identifiable alongside the midterm dummy).
    house_nat = national_house_two_party()
    missing = sorted({r["year"] for r in rows} - house_nat.keys())
    if missing:
        raise SenateTrainError(
            f"no national House two-party share for cycles {missing}; add them to "
            "NATIONAL_HOUSE_OVERRIDE with a source"
        )
    for row in rows:
        row["nat_env"] = round(house_nat[row["year"]] - 0.5, 6)
    return rows


def write_training_csv(rows: list[dict[str, Any]], dest: Path | None = None) -> Path:
    path = dest or TRAIN_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(TRAIN_FIELDS))
        w.writeheader()
        for row in rows:
            w.writerow({k: row[k] for k in TRAIN_FIELDS})
    return path
