"""Canonical midterm race registry (`data/races.json`, Prompt 10).

Join key for incumbents is still `bioguide_id`. FEC IDs are fundraising keys only.
`days_until_election` is a build-time derived field (as_of export date), never
persisted in DuckDB (AGENTS.md §8).
"""

from __future__ import annotations

import json
import re
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from vact.paths import REPO_ROOT

RACES_PATH = REPO_ROOT / "data" / "races.json"
TRACKED_RACE_IDS = frozenset(
    {f"va-{n:02d}" for n in range(1, 12)} | {"va-sen"}
)
SENATE_RACE_ID_RE = re.compile(r"^va-sen(-\d{4})?$")
HOUSE_RACE_ID_RE = re.compile(r"^va-\d{2}$")


class RaceStatus(StrEnum):
    TRACKED = "tracked"
    WATCH = "watch"


class Chamber(StrEnum):
    HOUSE = "House"
    SENATE = "Senate"


class PriorFederalService(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chamber: Literal["House", "Senate"]
    congresses: list[int] = Field(min_length=1)
    bioguide_id: str


class Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    party: Literal["Democrat", "Republican"]
    fec_candidate_id: str
    bioguide_id: str | None = None
    prior_federal_service: list[PriorFederalService] | None = None

    @field_validator("fec_candidate_id")
    @classmethod
    def _fec_id(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("fec_candidate_id is required")
        return text


class LeanPoint(BaseModel):
    """One presidential cycle's two-party Democratic share for this geography."""

    model_config = ConfigDict(extra="forbid")

    year: int
    dem_two_party: float = Field(gt=0.0, lt=1.0)
    map_version: str
    precision: Literal["exact_votes", "rounded_percent"]
    source_url: str

    @field_validator("year")
    @classmethod
    def _presidential(cls, value: int) -> int:
        if value % 4 != 0:
            raise ValueError(f"{value} is not a presidential year")
        return value


class DistrictLean(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pres_2020_two_party_dem_share: float | None = None
    pres_2024_two_party_dem_share: float | None = None
    source_url: str
    # Ordered oldest-first. Every point must share a map_version: comparing a
    # district across cycles is only meaningful under one set of boundaries.
    history: list[LeanPoint] = Field(default_factory=list)

    @model_validator(mode="after")
    def _one_map_version(self) -> DistrictLean:
        maps = {p.map_version for p in self.history}
        if len(maps) > 1:
            raise ValueError(
                f"district_lean.history mixes map versions {sorted(maps)}; a district "
                "number means different geography under each, so the trend is not comparable"
            )
        years = [p.year for p in self.history]
        if years != sorted(years):
            raise ValueError("district_lean.history must be ordered oldest-first")
        if len(years) != len(set(years)):
            raise ValueError("district_lean.history has duplicate years")
        return self

    @field_validator("source_url")
    @classmethod
    def _source(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("district_lean.source_url is required (placeholder OK)")
        return text


class Rating(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outlet: str
    rating: str
    as_of: str
    source_url: str


class Race(BaseModel):
    model_config = ConfigDict(extra="forbid")

    race_id: str
    chamber: Chamber = Chamber.HOUSE
    district: int | None = None
    election_date: date
    status: RaceStatus
    incumbent: Candidate
    challenger: Candidate
    district_lean: DistrictLean
    ratings: list[Rating] = Field(default_factory=list)

    @field_validator("race_id")
    @classmethod
    def _race_id(cls, value: str) -> str:
        text = value.strip().lower()
        if not (HOUSE_RACE_ID_RE.match(text) or SENATE_RACE_ID_RE.match(text)):
            raise ValueError(f"race_id must look like va-01 or va-sen, got {value!r}")
        return text

    @model_validator(mode="after")
    def _chamber_matches_geography(self) -> Race:
        """District is the House join key; a statewide Senate race must not carry one."""
        if self.chamber is Chamber.HOUSE:
            if self.district is None:
                raise ValueError(f"{self.race_id}: House races require a district number")
            if not HOUSE_RACE_ID_RE.match(self.race_id):
                raise ValueError(f"{self.race_id}: House race_id must look like va-01")
        else:
            if self.district is not None:
                raise ValueError(
                    f"{self.race_id}: Senate races are statewide; district must be null"
                )
            if not SENATE_RACE_ID_RE.match(self.race_id):
                raise ValueError(f"{self.race_id}: Senate race_id must look like va-sen")
        return self

    @model_validator(mode="after")
    def _tracked_requires_ids(self) -> Race:
        if self.status is RaceStatus.TRACKED:
            if not self.election_date:
                raise ValueError(f"{self.race_id}: tracked races need election_date")
            if not self.incumbent.fec_candidate_id or not self.challenger.fec_candidate_id:
                raise ValueError(f"{self.race_id}: tracked races need both fec_candidate_id values")
            if not self.incumbent.bioguide_id:
                raise ValueError(f"{self.race_id}: incumbent bioguide_id required")
        return self


class RaceRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    map_version: str
    election_date: date
    notes: str = ""
    races: list[Race]

    @model_validator(mode="after")
    def _require_tracked_set(self) -> RaceRegistry:
        ids = {r.race_id for r in self.races if r.status is RaceStatus.TRACKED}
        missing = TRACKED_RACE_IDS - ids
        if missing:
            raise ValueError(f"missing tracked races: {sorted(missing)}")
        seen: set[str] = set()
        for race in self.races:
            if race.race_id in seen:
                raise ValueError(f"duplicate race_id {race.race_id}")
            seen.add(race.race_id)
            if race.election_date != self.election_date:
                raise ValueError(
                    f"{race.race_id}: election_date {race.election_date} "
                    f"!= registry {self.election_date}"
                )
        return self


CONGRESS_TERMS_PATH = REPO_ROOT / "config" / "congress_terms.yaml"


def verify_bioguide_ids(registry: RaceRegistry | None = None) -> list[str]:
    """Check every bioguide id against the congress-legislators roster.

    A wrong id is the most dangerous error in this file, because it fails
    silently in the worst direction: `P000601` was committed for Tom Perriello
    when it belongs to Steven Palazzo (MS-4, Republican). While the 116th and
    117th were unbackfilled it returned zero rows and looked exactly like
    "no data yet"; the moment those congresses were ingested it started
    resolving, and the head-to-head would have published a Mississippi
    Republican's roll calls under Perriello's name.

    Returns a list of problems; empty means clean.
    """
    import yaml

    from vact.sources import legislators as legislator_source

    reg = registry or load_races()
    paths = legislator_source.fetch_all()
    people = legislator_source.parse_legislators(
        paths["legislators-current"]
    ) + legislator_source.parse_legislators(paths["legislators-historical"])
    by_id = {p.id.bioguide: p for p in people}
    terms_cfg = yaml.safe_load(CONGRESS_TERMS_PATH.read_text(encoding="utf-8"))["terms"]

    problems: list[str] = []
    for race in reg.races:
        state = race.race_id.split("-")[0].upper()

        inc_id = race.incumbent.bioguide_id
        if inc_id:
            person = by_id.get(inc_id)
            if person is None:
                problems.append(f"{race.race_id}: incumbent bioguide {inc_id} not in roster")
            elif not any(t.state == state for t in person.terms):
                problems.append(
                    f"{race.race_id}: incumbent {inc_id} "
                    f"({person.name.official_full or person.name.last}) never served {state}"
                )

        for svc in race.challenger.prior_federal_service or []:
            person = by_id.get(svc.bioguide_id)
            if person is None:
                problems.append(
                    f"{race.race_id}: challenger bioguide {svc.bioguide_id} not in roster"
                )
                continue
            label = person.name.official_full or person.name.last
            if not any(t.state == state for t in person.terms):
                problems.append(
                    f"{race.race_id}: {svc.bioguide_id} is {label}, who never served {state} "
                    f"(claimed as {race.challenger.name})"
                )
            want_chamber = "rep" if svc.chamber == "House" else "sen"
            for congress in svc.congresses:
                window = terms_cfg.get(congress)
                if window is None:
                    problems.append(
                        f"{race.race_id}: congress {congress} missing from congress_terms.yaml"
                    )
                    continue
                lo, hi = str(window["start"]), str(window["end"])
                served = any(
                    t.type == want_chamber
                    and str(t.start) < hi
                    and str(t.end) > lo
                    for t in person.terms
                )
                if not served:
                    problems.append(
                        f"{race.race_id}: {label} ({svc.bioguide_id}) has no {svc.chamber} "
                        f"term overlapping the {congress}th Congress"
                    )
    return problems


class RacesValidationError(ValueError):
    """Registry failed structural / business-rule validation."""


def load_races(path: Path | None = None) -> RaceRegistry:
    dest = path or RACES_PATH
    if not dest.is_file():
        raise RacesValidationError(f"races.json not found: {dest}")
    payload = json.loads(dest.read_text(encoding="utf-8"))
    try:
        return RaceRegistry.model_validate(payload)
    except Exception as err:  # noqa: BLE001 — surface pydantic errors as validation failures
        raise RacesValidationError(str(err)) from err


def validate_races(path: Path | None = None) -> RaceRegistry:
    """Fail loud if schema or tracked-race requirements fail."""
    return load_races(path)


def race_label(race: Race) -> str:
    """Display label: `VA-2` for House seats, `VA-Sen` for the statewide race."""
    if race.chamber is Chamber.SENATE:
        return "VA-Sen"
    return f"VA-{race.district}"


def house_races(registry: RaceRegistry | None = None) -> list[Race]:
    """House races only. The seat model is fit on House contests (AGENTS §8)."""
    reg = registry or load_races()
    return [r for r in reg.races if r.chamber is Chamber.HOUSE]


def days_until_election(election_date: date, *, as_of: date | None = None) -> int:
    """Calendar days from as_of to election_date. Negative after election day.

    as_of defaults to today at call time. Prefer passing an explicit as_of from
    export so tests stay deterministic.
    """
    day = as_of if as_of is not None else date.today()
    return (election_date - day).days


def races_for_web(
    registry: RaceRegistry | None = None,
    *,
    as_of: date | None = None,
) -> dict[str, Any]:
    """Serialize registry with build-time days_until_election per race."""
    reg = registry or load_races()
    day = as_of if as_of is not None else date.today()
    races = []
    for race in reg.races:
        payload = race.model_dump(mode="json")
        payload["days_until_election"] = days_until_election(race.election_date, as_of=day)
        payload["label"] = race_label(race)
        races.append(payload)
    return {
        "version": reg.version,
        "map_version": reg.map_version,
        "election_date": reg.election_date.isoformat(),
        "as_of": day.isoformat(),
        "days_until_election": days_until_election(reg.election_date, as_of=day),
        "notes": reg.notes,
        "races": races,
    }


def all_fec_candidate_ids(registry: RaceRegistry | None = None) -> list[str]:
    reg = registry or load_races()
    ids: list[str] = []
    for race in reg.races:
        if race.status is not RaceStatus.TRACKED:
            continue
        ids.append(race.incumbent.fec_candidate_id)
        ids.append(race.challenger.fec_candidate_id)
    return ids
