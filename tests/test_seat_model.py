"""Seat model tests (Prompt 13)."""

from __future__ import annotations

from datetime import date

import pytest

from vact.analysis.seat_model import (
    load_seat_config,
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


def test_predict_all_tracked_house_races() -> None:
    payload = predict_races(as_of=date(2026, 8, 19), fit=load_fit())
    ids = {r["race_id"] for r in payload["races"]}
    assert ids == {f"va-{n:02d}" for n in range(1, 12)}
    grid = payload["env_grid"]
    assert grid["margin_pp"][0] == -4.0
    assert grid["margin_pp"][-1] == 12.0
    assert len(grid["margin_pp"]) == 33
    for race in payload["races"]:
        assert 0.0 <= race["prob_dem"] <= 1.0
        assert race["share_lo"] <= race["mu_dem_two_party"] <= race["share_hi"]
        assert "intercept" in race["decomposition"]
        assert race["blend"] == "fundamentals_only"
        assert race["model_version"] == load_seat_config()["model_version"]
        assert race["takeaway"].startswith("VA-")
        assert "vote" not in race["takeaway"].lower()
        assert len(race["env_probs"]) == 33
        assert grid["probs"][race["race_id"]] == race["env_probs"]


def test_env_grid_monotonic_and_flip_threshold() -> None:
    from vact.analysis.seat_model import (
        env_margin_grid,
        flip_threshold_pp,
        interpolate_grid,
        takeaway_sentence,
    )

    margins = env_margin_grid()
    # Synthetic: crosses 0.5 at D+2.0
    probs = [0.2 + 0.1 * (m + 4) / 2 for m in margins]
    # that's not crossing at 2... just test helpers
    probs = [0.40 if m < 2.0 else 0.55 for m in margins]
    assert flip_threshold_pp(margins, probs) == 2.0
    sentence = takeaway_sentence(district=1, margins=margins, probs=probs)
    assert "D+2" in sentence
    assert interpolate_grid(margins, probs, 1.75) < 0.55
    always = [0.8] * len(margins)
    assert "stays above 50%" in takeaway_sentence(district=2, margins=margins, probs=always)
    never = [0.2] * len(margins)
    assert "stays below 50%" in takeaway_sentence(district=5, margins=margins, probs=never)


def test_training_extract_incumbency_is_not_contaminated() -> None:
    """seat-v1.0 coded 27.8% of races open because top-two and fusion races were
    dropped from the winner index; qual_dem then absorbed the misclassified
    safe-seat incumbents at +12.5pp. Guard both symptoms."""
    import csv
    import statistics

    from vact.analysis.seat_model import TRAIN_PATH

    rows = list(csv.DictReader(TRAIN_PATH.open(encoding="utf-8", newline="")))
    open_rate = sum(1 for r in rows if r["inc_dem"] == "0") / len(rows)
    assert open_rate < 0.22, f"open-seat rate {open_rate:.3f} back near the v1.0 defect"

    qual_pos = [float(r["dem_two_party"]) for r in rows if r["qual_dem"] == "1"]
    base = [float(r["dem_two_party"]) for r in rows if r["qual_dem"] == "0"]
    assert qual_pos, "no qual_dem=1 rows at all — the flag stopped firing"
    # A real quality signal is a few points, not the 20pp gap v1.0 produced.
    assert statistics.mean(qual_pos) - statistics.mean(base) < 0.12
