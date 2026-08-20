"""Seat model tests (Prompt 13)."""

from __future__ import annotations

from datetime import date

import pytest

from vact.analysis.seat_model import (
    OLS_FEATURES,
    SeatModelError,
    blend_mu,
    fit_seat_model,
    load_fit,
    load_training_csv,
    poll_average,
    predict_races,
    prior_presidential_year,
    validate_predictions_append_only,
)


def test_prior_presidential_year() -> None:
    assert prior_presidential_year(2010) == 2008
    assert prior_presidential_year(2012) == 2008
    assert prior_presidential_year(2018) == 2016
    assert prior_presidential_year(2020) == 2016
    assert prior_presidential_year(2022) == 2020
    assert prior_presidential_year(2026) == 2024


def test_blend_no_polls_is_fundamentals() -> None:
    mu, sigma, label = blend_mu(0.47, 0.06, None)
    assert mu == 0.47
    assert sigma == 0.06
    assert label == "fundamentals_only"


def test_blend_converges_to_poll_as_n_grows() -> None:
    mu_f, sigma_f = 0.40, 0.08
    weak = {"mu": 0.55, "sigma": 0.10}
    strong = {"mu": 0.55, "sigma": 0.001}
    mu_w, _, _ = blend_mu(mu_f, sigma_f, weak)
    mu_s, _, label = blend_mu(mu_f, sigma_f, strong)
    assert abs(mu_s - 0.55) < abs(mu_w - 0.55)
    assert abs(mu_s - 0.55) < 0.002
    assert label == "fundamentals_plus_polls"


def test_poll_average_recency_half_life() -> None:
    rows = [
        {
            "race_id": "va-02",
            "end_date": "2026-08-01",
            "n": "400",
            "dem_share": "40",
            "rep_share": "60",
        },
        {
            "race_id": "va-02",
            "end_date": "2026-08-18",
            "n": "400",
            "dem_share": "60",
            "rep_share": "40",
        },
    ]
    avg = poll_average("va-02", as_of=date(2026, 8, 19), half_life_days=14, rows=rows)
    assert avg is not None
    assert avg["mu"] > 0.50


def test_append_only_rejects_mutation() -> None:
    prev = [
        {
            "race_id": "va-01",
            "date": "2026-08-19",
            "prob_dem": "0.3100",
            "model_version": "seat-v1.0",
        }
    ]
    cur = [
        {
            "race_id": "va-01",
            "date": "2026-08-19",
            "prob_dem": "0.4000",
            "model_version": "seat-v1.0",
        }
    ]
    with pytest.raises(SeatModelError, match="mutated"):
        validate_predictions_append_only(cur, prev)


def test_append_only_rejects_deletion() -> None:
    prev = [
        {
            "race_id": "va-01",
            "date": "2026-08-19",
            "prob_dem": "0.3100",
            "model_version": "seat-v1.0",
        },
        {
            "race_id": "va-02",
            "date": "2026-08-19",
            "prob_dem": "0.4400",
            "model_version": "seat-v1.0",
        },
    ]
    cur = [prev[0]]
    with pytest.raises(SeatModelError, match="missing"):
        validate_predictions_append_only(cur, prev)


def test_fit_and_holdout_brier_in_summary() -> None:
    rows = load_training_csv()
    summary = fit_seat_model(rows)
    assert summary["n_train"] > 200
    assert summary["n_holdout"] >= 8
    assert summary["holdout_brier"] is not None
    assert summary["holdout_always_incumbent_brier"] is not None
    assert set(summary["ols_beta"]) == set(OLS_FEATURES)
    assert summary["ols_beta"]["lean_rel_dem"] > 0
    assert summary["ols_beta"]["inc_dem"] > 0


def test_predict_three_tracked_races() -> None:
    payload = predict_races(as_of=date(2026, 8, 19), fit=load_fit())
    ids = {r["race_id"] for r in payload["races"]}
    assert ids == {"va-01", "va-02", "va-05"}
    for race in payload["races"]:
        assert 0.0 <= race["prob_dem"] <= 1.0
        assert race["share_lo"] <= race["mu_dem_two_party"] <= race["share_hi"]
        assert "intercept" in race["decomposition"]
        assert race["blend"] == "fundamentals_only"
        assert race["model_version"] == "seat-v1.0"
