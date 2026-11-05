"""Scoring published forecasts against returns."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vact.analysis.forecast_scoring import load_results, score


def _results(path: Path) -> Path:
    path.write_text(
        "race_id,dem_votes,rep_votes,localities_reporting,localities_total,status,source_url,retrieved_at_utc\n"
        "va-01,60,40,5,5,unofficial,https://example.invalid,2026-11-05T00:00:00Z\n"
        "va-02,40,60,4,5,unofficial,https://example.invalid,2026-11-05T00:00:00Z\n",
        encoding="utf-8",
    )
    return path


def _payload(path: Path, races: list[dict]) -> Path:
    path.write_text(json.dumps({"races": races}), encoding="utf-8")
    return path


def test_results_parse_two_party_and_completeness(tmp_path: Path) -> None:
    rows = load_results(_results(tmp_path / "r.csv"))
    assert rows["va-01"]["dem_two_party"] == 0.6
    assert rows["va-01"]["dem_won"] is True
    assert rows["va-01"]["complete"] is True
    # A race still counting must be flagged, because a late locality can flip the
    # call: va-05 led on election night and lost once the last locality reported.
    assert rows["va-02"]["complete"] is False


def test_scoring_rewards_a_right_call_and_punishes_a_confident_wrong_one(tmp_path: Path) -> None:
    seats = _payload(tmp_path / "seats.json", [
        {"race_id": "va-01", "prob_dem": 0.9, "mu_dem_two_party": 0.60, "model_version": "t"},
        {"race_id": "va-02", "prob_dem": 0.9, "mu_dem_two_party": 0.60, "model_version": "t"},
    ])
    senate = _payload(tmp_path / "senate.json", [])
    rep = score(results_path=_results(tmp_path / "r.csv"), published_paths=(seats, senate))
    by_id = {r["race_id"]: r for r in rep["races"]}
    assert by_id["va-01"]["called"] is True
    assert by_id["va-02"]["called"] is False
    # Same probability, opposite outcomes: Brier must be symmetric around it.
    assert by_id["va-01"]["brier"] + by_id["va-02"]["brier"] == pytest.approx(0.82)
    assert rep["all"]["winners_called"] == 1
    # va-02 was predicted 0.60 and came in 0.40, so the bias is +10 points per race.
    assert rep["all"]["share_bias_pp"] == pytest.approx(10.0)
    assert rep["incomplete_races"] == ["va-02"]


def test_live_scoring_runs_on_committed_results() -> None:
    """Guards the committed artifact: the record must stay reproducible."""
    rep = score()
    assert rep["all"]["n"] == 12
    assert rep["competitive"]["n"] >= 1
    assert 0.0 <= rep["all"]["brier"] <= 1.0
    assert rep["baselines"]["always_incumbent_brier"] is not None
