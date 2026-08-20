"""Tests for the beta-binomial empirical Bayes estimator (Prompt 2)."""

from __future__ import annotations

import numpy as np
import pytest

from vact.analysis.estimators import (
    BetaPrior,
    attach_empirical_bayes,
    estimate_member_theme,
    fit_beta_moments,
    fit_caucus_prior,
)
from vact.analysis.scoring import load_scoring_config, wilson_interval
from vact.analysis.scoring import signed_score_from_counts


def test_low_n_shrinks_toward_caucus_mean() -> None:
    prior = fit_caucus_prior(
        ks=[8] * 8 + [0],
        ns=[10] * 8 + [3],
        method="moments",
        min_caucus=3,
    )
    assert prior.source in {"moments", "mle"}
    low = estimate_member_theme(0, 3, prior)
    assert low.raw_score == -1.0
    # Shrinkage is toward the caucus (positive), not past it.
    assert low.eb_score > low.raw_score
    assert low.eb_score < prior.signed_center


def test_high_n_moves_less_than_low_n() -> None:
    prior = fit_caucus_prior(
        ks=[8] * 8,
        ns=[10] * 8,
        method="moments",
        min_caucus=3,
    )
    low = estimate_member_theme(0, 3, prior)
    high = estimate_member_theme(0, 40, prior)
    assert abs(low.eb_score - low.raw_score) > abs(high.eb_score - high.raw_score)


def test_posterior_interval_narrower_than_wilson_at_equal_n() -> None:
    """Member sitting on the prior mean: EB interval should beat Wilson."""
    prior = BetaPrior(alpha=12.0, beta=12.0, source="moments", n_members=10)
    n, k = 10, 5
    est = estimate_member_theme(k, n, prior)
    w_lo, w_hi = wilson_interval(k, n, 1.96)
    wilson_width = (2 * w_hi - 1) - (2 * w_lo - 1)
    cred_width = est.cred_hi - est.cred_lo
    assert cred_width < wilson_width


def test_n_zero_is_prior_only() -> None:
    prior = BetaPrior(alpha=4.0, beta=6.0, source="moments", n_members=5)
    est = estimate_member_theme(0, 0, prior)
    assert est.prior_only
    assert est.raw_score is None
    assert est.eb_score == pytest.approx(prior.signed_center, abs=1e-4)


def test_small_caucus_falls_back_to_beta_2_2() -> None:
    prior = fit_caucus_prior(ks=[1, 0], ns=[2, 1], method="moments", min_caucus=3)
    assert prior.source == "weakly_informative"
    assert prior.alpha == 2.0
    assert prior.beta == 2.0


def test_attach_writes_prompt_fields() -> None:
    cfg = load_scoring_config()
    frame = [
        {
            "bioguide_id": f"M{i}",
            "full_name": f"M{i}",
            "party": "Democrat",
            "chamber": "House",
            "district_number": i,
            "impact_tag": "INPUT_COSTS",
            "n_contested": 6,
            "n_yea": 6,
            "n_nay": 0,
            "n_not_voting": 0,
            "n_present": 0,
            "n_pro": 5 if i < 4 else 1,
            "signed_score": signed_score_from_counts(5 if i < 4 else 1, 6, 1.96)["signed_score"],
            "wilson_low": -0.5,
            "wilson_high": 0.5,
            "sufficient": True,
            "absence_rate": 0.0,
            "map_version": "2021",
        }
        for i in range(6)
    ]
    out, baselines = attach_empirical_bayes(frame, cfg)
    assert all("eb_score" in r and "k" in r and "prior_alpha" in r for r in out)
    assert baselines and baselines[0]["party"] == "Democrat"
    assert baselines[0]["theme"] == "INPUT_COSTS"
    assert "eb_center" in baselines[0]


def test_synthetic_eb_rmse_beats_raw() -> None:
    """500 members from a known Beta; EB posterior mean should beat raw p."""
    rng = np.random.default_rng(42)
    true_a, true_b = 8.0, 4.0
    p = rng.beta(true_a, true_b, size=500)
    n = rng.integers(4, 25, size=500)
    k = rng.binomial(n, p)
    prior = fit_caucus_prior(k.tolist(), n.tolist(), method="moments", min_caucus=3)
    eb = np.array(
        [(prior.alpha + ki) / (prior.alpha + prior.beta + ni) for ki, ni in zip(k, n)]
    )
    raw = k / n
    rmse_eb = float(np.sqrt(np.mean((eb - p) ** 2)))
    rmse_raw = float(np.sqrt(np.mean((raw - p) ** 2)))
    assert rmse_eb < rmse_raw


def test_mom_none_when_single_observation() -> None:
    assert fit_beta_moments([3], [4]) is None


def test_unanimous_caucus_does_not_use_beta_2_2() -> None:
    """A caucus at p=1 must not shrink toward 0.5 via the weak fallback."""
    prior = fit_caucus_prior(ks=[4] * 5, ns=[4] * 5, method="moments", min_caucus=3)
    assert prior.source == "degenerate"
    assert prior.mean > 0.9
    loyalist = estimate_member_theme(4, 4, prior)
    dissenter = estimate_member_theme(0, 3, prior)
    assert loyalist.eb_score > 0.9
    assert dissenter.raw_score == -1.0
    assert dissenter.eb_score > -0.5
    assert abs(loyalist.eb_score - loyalist.raw_score) < abs(
        dissenter.eb_score - (dissenter.raw_score or 0.0)
    )
