"""Build the committed House-race training extract from MEDSL candidate rows."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Iterable

from vact.analysis.seat_model import (
    RaceRow,
    SeatModelError,
    TRAIN_PATH,
    _district_key,
    _midterm_dem,
    _norm_name,
    _party_family,
    load_seat_config,
    prior_presidential_year,
    write_training_csv,
)


def aggregate_house_races(raw_rows: Iterable[dict[str, str]]) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in raw_rows:
        if row.get("stage", "").upper() != "GEN":
            continue
        if str(row.get("special", "")).upper() == "TRUE":
            continue
        if str(row.get("mode", "")).upper() != "TOTAL":
            continue
        if str(row.get("writein", "")).upper() == "TRUE":
            continue
        year = int(row["year"])
        fam = _party_family(row.get("party") or "")
        if fam is None:
            continue
        key = (str(year), row["state_po"], row["district"])
        bucket = buckets.setdefault(
            key,
            {
                "year": year,
                "state_po": row["state_po"],
                "district": row["district"],
                "dem_votes": 0.0,
                "rep_votes": 0.0,
                "dem_name": "",
                "rep_name": "",
                "dem_name_votes": -1.0,
                "rep_name_votes": -1.0,
            },
        )
        votes = float(row.get("candidatevotes") or 0.0)
        name = row.get("candidate") or ""
        if fam == "Democrat":
            bucket["dem_votes"] += votes
            if votes > bucket["dem_name_votes"]:
                bucket["dem_name"] = name
                bucket["dem_name_votes"] = votes
        else:
            bucket["rep_votes"] += votes
            if votes > bucket["rep_name_votes"]:
                bucket["rep_name"] = name
                bucket["rep_name_votes"] = votes
    races = []
    for bucket in buckets.values():
        dem = bucket["dem_votes"]
        rep = bucket["rep_votes"]
        if dem <= 0 or rep <= 0:
            continue
        two = dem + rep
        races.append(
            {
                "year": bucket["year"],
                "state_po": bucket["state_po"],
                "district": bucket["district"],
                "race_key": _district_key(bucket["state_po"], bucket["district"]),
                "dem_votes": dem,
                "rep_votes": rep,
                "dem_two_party": dem / two,
                "dem_winner": dem > rep,
                "dem_name": bucket["dem_name"],
                "rep_name": bucket["rep_name"],
            }
        )
    return races


def _national_dem_share(races: list[dict[str, Any]], year: int) -> float:
    dem = sum(r["dem_votes"] for r in races if r["year"] == year)
    rep = sum(r["rep_votes"] for r in races if r["year"] == year)
    if dem + rep <= 0:
        raise SeatModelError(f"no two-party votes for national environment {year}")
    return dem / (dem + rep)


def build_training_rows(
    raw_rows: Iterable[dict[str, str]],
    *,
    config: dict[str, Any] | None = None,
) -> list[RaceRow]:
    cfg = config or load_seat_config()
    races = aggregate_house_races(raw_rows)
    by_year_key: dict[tuple[int, str], dict[str, Any]] = {
        (r["year"], r["race_key"]): r for r in races
    }
    winners_by_year: dict[int, dict[str, str]] = {}
    for r in races:
        winners_by_year.setdefault(r["year"], {})[r["race_key"]] = (
            "Democrat" if r["dem_winner"] else "Republican"
        )
        winners_by_year[r["year"]][f"name:{r['race_key']}:Democrat"] = _norm_name(r["dem_name"])
        winners_by_year[r["year"]][f"name:{r['race_key']}:Republican"] = _norm_name(r["rep_name"])

    quality_names: set[str] = set()
    holdout_ids = {d.upper() for d in cfg["holdout"]["districts"]}
    train_years = {int(y) for y in cfg["train_years"]}
    pres = {int(k): v for k, v in cfg["president_party_by_cycle"].items()}

    rows: list[RaceRow] = []
    for year in sorted({r["year"] for r in races}):
        nat = _national_dem_share(races, year)
        lean_year = prior_presidential_year(year)
        try:
            nat_lean_year = _national_dem_share(races, lean_year)
        except SeatModelError:
            nat_lean_year = None
        pres_party = pres.get(year)
        year_races = [x for x in races if x["year"] == year]
        for r in year_races:
            dem_n = _norm_name(r["dem_name"])
            rep_n = _norm_name(r["rep_name"])
            prev = winners_by_year.get(year - 2, {})
            prev_party = prev.get(r["race_key"])
            prev_dem = prev.get(f"name:{r['race_key']}:Democrat")
            prev_rep = prev.get(f"name:{r['race_key']}:Republican")
            incumbent_party = None
            if prev_party == "Democrat" and dem_n and dem_n == prev_dem:
                incumbent_party = "Democrat"
            elif prev_party == "Republican" and rep_n and rep_n == prev_rep:
                incumbent_party = "Republican"
            inc_dem = 1 if incumbent_party == "Democrat" else -1 if incumbent_party == "Republican" else 0
            qual_dem = 0
            if incumbent_party == "Republican" and dem_n in quality_names:
                qual_dem = 1
            elif incumbent_party == "Democrat" and rep_n in quality_names:
                qual_dem = -1
            elif incumbent_party is None:
                if dem_n in quality_names and rep_n not in quality_names:
                    qual_dem = 1
                elif rep_n in quality_names and dem_n not in quality_names:
                    qual_dem = -1
            lag = by_year_key.get((lean_year, r["race_key"]))
            if lag is not None and nat_lean_year is not None:
                lean_rel = lag["dem_two_party"] - nat_lean_year
            else:
                lean_rel = 0.0
            holdout = year == int(cfg["holdout"]["year"]) and r["race_key"] in holdout_ids
            if (year in train_years or holdout) and pres_party:
                rows.append(
                    RaceRow(
                        year=year,
                        race_key=r["race_key"],
                        state_po=r["state_po"],
                        district=int(str(r["district"]).lstrip("0") or "0"),
                        dem_votes=r["dem_votes"],
                        rep_votes=r["rep_votes"],
                        dem_two_party=r["dem_two_party"],
                        dem_winner=r["dem_winner"],
                        dem_name=r["dem_name"],
                        rep_name=r["rep_name"],
                        incumbent_party=incumbent_party,
                        lean_rel_dem=lean_rel,
                        inc_dem=inc_dem,
                        midterm_dem=_midterm_dem(year, str(pres_party)),
                        log_ratio_dem=0.0,
                        qual_dem=qual_dem,
                        nat_env=nat - 0.5,
                        holdout=holdout,
                    )
                )
        for r in year_races:
            quality_names.add(_norm_name(r["dem_name"] if r["dem_winner"] else r["rep_name"]))
    return rows


def build_training_csv_from_medsl(medsl_path: Path, dest: Path | None = None) -> Path:
    with medsl_path.open(encoding="utf-8", newline="") as fh:
        raw = list(csv.DictReader(fh))
    rows = build_training_rows(raw)
    return write_training_csv(rows, dest or TRAIN_PATH)
