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


def plurality_winners(raw_rows: Iterable[dict[str, str]]) -> dict[tuple[int, str], str]:
    """(year, race_key) -> normalized name of the plurality winner.

    Built from every general-election race, including ones the two-party frame
    drops: California/Washington top-two finals with no major-party opponent, and
    New York fusion races where only a minor party fielded the opposition. Those
    drops were breaking the incumbency chain for exactly the safest, longest-
    serving members, who then entered training as open seats (seat-v1.0 coded
    27.8% of races open against a real rate near 10%).

    Fusion rows are summed per candidate before the winner is taken.
    """
    tally: dict[tuple[int, str], dict[str, float]] = {}
    for row in raw_rows:
        if row.get("stage", "").upper() != "GEN":
            continue
        if str(row.get("special", "")).upper() == "TRUE":
            continue
        if str(row.get("mode", "")).upper() != "TOTAL":
            continue
        if str(row.get("writein", "")).upper() == "TRUE":
            continue
        name = _norm_name(row.get("candidate") or "")
        if not name or "BLANK VOTE" in (row.get("candidate") or "").upper():
            continue
        key = (int(row["year"]), _district_key(row["state_po"], row["district"]))
        votes = float(row.get("candidatevotes") or 0.0)
        tally.setdefault(key, {})
        tally[key][name] = tally[key].get(name, 0.0) + votes
    return {
        key: max(names.items(), key=lambda kv: kv[1])[0]
        for key, names in tally.items()
        if names
    }


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
    raw_list = list(raw_rows)
    races = aggregate_house_races(raw_list)
    # Incumbency and challenger quality come from the all-races winner index, not
    # from the two-party frame, so top-two and fusion races stay in the chain.
    winners_all = plurality_winners(raw_list)
    by_year_key: dict[tuple[int, str], dict[str, Any]] = {
        (r["year"], r["race_key"]): r for r in races
    }
    # name -> every year that name won a House seat. Judging quality as-of each
    # cycle (rather than "ever won") is what separates a genuine former member
    # returning from a sitting member, which is what inflated qual_dem in v1.0.
    win_years: dict[str, set[int]] = {}
    for (win_year, _key), winner in winners_all.items():
        if winner:
            win_years.setdefault(winner, set()).add(win_year)
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
            prev_winner = winners_all.get((year - 2, r["race_key"]))
            incumbent_party = None
            if prev_winner and dem_n and dem_n == prev_winner:
                incumbent_party = "Democrat"
            elif prev_winner and rep_n and rep_n == prev_winner:
                incumbent_party = "Republican"
            inc_dem = 1 if incumbent_party == "Democrat" else -1 if incumbent_party == "Republican" else 0
            def _is_quality(name: str) -> bool:
                """Won a House seat at least two cycles back, and not in the
                immediately preceding one. A win at year-2 means a sitting member,
                not a returning challenger."""
                if not name:
                    return False
                years_won = win_years.get(name)
                if not years_won or (year - 2) in years_won:
                    return False
                return any(w <= year - 4 for w in years_won)

            dem_q = _is_quality(dem_n)
            rep_q = _is_quality(rep_n)
            qual_dem = 0
            if incumbent_party == "Republican" and dem_q:
                qual_dem = 1
            elif incumbent_party == "Democrat" and rep_q:
                qual_dem = -1
            elif incumbent_party is None:
                if dem_q and not rep_q:
                    qual_dem = 1
                elif rep_q and not dem_q:
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
    return rows


def build_training_csv_from_medsl(medsl_path: Path, dest: Path | None = None) -> Path:
    with medsl_path.open(encoding="utf-8", newline="") as fh:
        raw = list(csv.DictReader(fh))
    rows = build_training_rows(raw)
    return write_training_csv(rows, dest or TRAIN_PATH)
