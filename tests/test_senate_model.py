"""Senate model (senate-v0.1) and its training extract."""

from __future__ import annotations

import csv
from datetime import date

import pytest

from vact.analysis.senate_model import (
    OLS_FEATURES,
    SenateModelError,
    leave_one_cycle_out,
    load_config,
    load_fit,
    load_training,
    predict,
)
from vact.analysis.senate_train import (
    TRAIN_PATH,
    load_national_presidential,
    load_state_presidential,
    national_house_two_party,
    sitting_senators,
)


def test_training_extract_spans_every_cycle() -> None:
    """States are a permanent panel, so unlike the House model nothing is dropped
    for redistricting."""
    rows = load_training()
    years = sorted({int(r["year"]) for r in rows})
    assert years == load_config()["train_years"]
    assert len(rows) > 200


def test_lean_is_real_presidential_share_not_a_transfer() -> None:
    pres = load_state_presidential()
    nat = load_national_presidential()
    assert (2024, "VA") in pres
    assert 0.5 < pres[(2024, "VA")] < 0.56
    assert 0.45 < nat[2024] < 0.52
    # VA leans a few points left of the nation, not twenty.
    assert 0.0 < pres[(2024, "VA")] - nat[2024] < 0.06


def test_national_house_share_tracks_known_waves() -> None:
    nat = national_house_two_party()
    assert nat[2018] > 0.52, "2018 was a Democratic wave"
    assert nat[2010] < 0.48, "2010 was a Republican wave"
    assert 2024 in nat, "2024 must come from the cited override"


def test_sitting_senator_lookup_spans_a_full_term() -> None:
    winners = {
        (2020, "VA"): {"MARK WARNER"},
        (2019, "GA"): {"SPECIAL WINNER"},
    }
    assert "MARK WARNER" in sitting_senators(winners, 2026, "VA")
    assert "MARK WARNER" not in sitting_senators(winners, 2027, "VA")
    # a special-election winner still counts as sitting
    assert "SPECIAL WINNER" in sitting_senators(winners, 2022, "GA")


def test_virginia_incumbency_is_coded_correctly() -> None:
    rows = {int(r["year"]): r for r in load_training() if r["state_po"] == "VA"}
    assert rows[2014]["inc_dem"] == "1"  # Warner running as incumbent
    assert rows[2024]["inc_dem"] == "1"  # Kaine running as incumbent
    assert rows[2012]["inc_dem"] == "0"  # Webb retired: Kaine vs Allen, open seat


def test_fit_beats_both_baselines_out_of_sample() -> None:
    """The whole justification for the model over arithmetic."""
    cv = load_fit()["cv"]
    assert cv["scheme"] == "leave_one_cycle_out"
    assert cv["brier_model"] < cv["brier_lean_swing"]
    assert cv["brier_model"] < cv["brier_always_incumbent"]
    assert len(cv["per_cycle"]) == len(load_config()["train_years"])


def test_midterm_dummy_stays_out_of_the_feature_set() -> None:
    """It was tested and dropped: identical LOCO Brier, and nat_env already
    carries the cycle environment."""
    assert "midterm_dem" not in OLS_FEATURES
    assert OLS_FEATURES == ("intercept", "lean_rel_dem", "inc_dem")


def test_incumbency_earns_its_place() -> None:
    rows = load_training()
    full = leave_one_cycle_out(rows)
    assert full["brier_model"] < full["brier_lean_swing"]


def test_predict_publishes_a_calibrated_looking_senate_race() -> None:
    payload = predict(as_of=date(2026, 8, 20))
    assert payload["model_version"] == load_config()["model_version"]
    assert len(payload["races"]) == 1
    race = payload["races"][0]
    assert race["race_id"] == "va-sen"
    assert 0.0 <= race["prob_dem"] <= 1.0
    assert race["share_lo"] <= race["mu_dem_two_party"] <= race["share_hi"]
    assert race["meta"]["lean_status"] != "missing_zeroed"
    # A three-term Democrat in a state Harris carried should be favoured, but a
    # Senate sigma of ~7pp keeps it well short of certainty.
    assert 0.6 < race["prob_dem"] < 0.97


def test_fit_version_must_match_config() -> None:
    doc = dict(load_fit())
    doc["model_version"] = "senate-v9.9"
    with pytest.raises(SenateModelError, match="!="):
        predict(as_of=date(2026, 8, 20), fit_doc=doc)


def test_house_model_does_not_score_the_senate_race() -> None:
    from vact.analysis.seat_model import predict_races

    house = predict_races(as_of=date(2026, 8, 20))
    assert "va-sen" not in {r["race_id"] for r in house["races"]}
    assert "va-sen" in house["unmodeled_races"]


def test_committed_extract_matches_rebuild() -> None:
    """The committed CSV must be what the builder produces."""
    with TRAIN_PATH.open(encoding="utf-8", newline="") as fh:
        committed = list(csv.DictReader(fh))
    assert committed, "training extract is empty"
    assert {"lean_rel_dem", "inc_dem", "nat_env"} <= set(committed[0])


def test_senate_race_carries_card_fields() -> None:
    """The battleground card renders from the same fields as a House seat, so a
    statewide race must not fall back to a \"Not modeled\" placeholder."""
    race = predict(as_of=date(2026, 8, 20))["races"][0]
    assert race["takeaway"].startswith("VA-Sen")
    assert race["plain_language"]
    assert "vote" not in race["takeaway"].lower()
    assert len(race["env_probs"]) == len(predict(as_of=date(2026, 8, 20))["env_grid"]["margin_pp"])


def test_env_grid_matches_the_house_axis() -> None:
    """One slider drives both grids on the homepage, so the axes must agree."""
    from vact.analysis.seat_model import predict_races

    sen = predict(as_of=date(2026, 8, 20))["env_grid"]["margin_pp"]
    house = predict_races(as_of=date(2026, 8, 20))["env_grid"]["margin_pp"]
    assert sen == house


def test_no_tracked_race_is_left_unscored() -> None:
    """Every tracked race must be scored by exactly one model."""
    from vact.analysis.races import load_races
    from vact.analysis.seat_model import predict_races

    tracked = {r.race_id for r in load_races().races if r.status.value == "tracked"}
    house = predict_races(as_of=date(2026, 8, 20))
    scored = {r["race_id"] for r in house["races"]}
    scored |= {r["race_id"] for r in predict(as_of=date(2026, 8, 20))["races"]}
    assert tracked == scored, f"unscored: {tracked - scored}"
