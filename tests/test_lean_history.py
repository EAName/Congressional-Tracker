"""District lean history: one map version per race, ordered, plausible."""

from __future__ import annotations

import json

import pytest

from vact.analysis.races import RACES_PATH, RacesValidationError, load_races, validate_races


def test_every_race_carries_a_lean_history() -> None:
    for race in validate_races(RACES_PATH).races:
        assert race.district_lean.history, f"{race.race_id} has no lean history"


def test_house_races_use_the_operative_map_only() -> None:
    """A district number means different geography under each map, so mixing
    cycles across maps would compare VA-2 to a different VA-2."""
    reg = validate_races(RACES_PATH)
    for race in reg.races:
        maps = {p.map_version for p in race.district_lean.history}
        assert len(maps) == 1, f"{race.race_id} mixes maps: {maps}"
        expected = "statewide" if race.chamber.value == "Senate" else reg.map_version
        assert maps == {expected}, f"{race.race_id} on {maps}, expected {expected}"


def test_statewide_reaches_further_back_than_districts() -> None:
    """State boundaries never moved, so the Senate race can show more cycles."""
    reg = validate_races(RACES_PATH)
    sen = next(r for r in reg.races if r.chamber.value == "Senate")
    house = next(r for r in reg.races if r.chamber.value == "House")
    assert len(sen.district_lean.history) > len(house.district_lean.history)
    assert len(sen.district_lean.history) == 5


def test_history_matches_the_field_the_model_reads() -> None:
    """The seat model reads pres_2024_two_party_dem_share. If the history's 2024
    point ever drifts from it, the chart and the forecast disagree."""
    for race in validate_races(RACES_PATH).races:
        pt = next((p for p in race.district_lean.history if p.year == 2024), None)
        assert pt is not None, f"{race.race_id} has no 2024 point"
        assert pt.dem_two_party == pytest.approx(
            race.district_lean.pres_2024_two_party_dem_share, abs=1e-6
        ), race.race_id


def test_mixed_map_versions_are_rejected(tmp_path) -> None:
    payload = json.loads(RACES_PATH.read_text(encoding="utf-8"))
    payload["races"][0]["district_lean"]["history"][0]["map_version"] = "2026"
    path = tmp_path / "races.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RacesValidationError, match="map versions"):
        load_races(path)


def test_out_of_order_history_is_rejected(tmp_path) -> None:
    payload = json.loads(RACES_PATH.read_text(encoding="utf-8"))
    payload["races"][0]["district_lean"]["history"].reverse()
    path = tmp_path / "races.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RacesValidationError, match="oldest-first"):
        load_races(path)
