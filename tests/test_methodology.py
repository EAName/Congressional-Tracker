"""Tests for the methodology payload (Prompt 3)."""

from __future__ import annotations

from vact.analysis.estimators import BetaPrior
from vact.analysis.methodology import (
    n_needed_to_separate,
    pick_worked_example,
    scoring_changelog,
)
from vact.analysis.scoring import load_scoring_config


def test_worked_example_picks_largest_shrinkage() -> None:
    scores = [
        {
            "sufficient": True,
            "raw_score": 1.0,
            "eb_score": 0.9,
            "n": 4,
            "k": 4,
            "bioguide_id": "A",
        },
        {
            "sufficient": True,
            "raw_score": -1.0,
            "eb_score": -0.2,
            "n": 3,
            "k": 0,
            "bioguide_id": "B",
        },
        {
            "sufficient": False,
            "raw_score": -1.0,
            "eb_score": 0.0,
            "n": 1,
            "k": 0,
            "bioguide_id": "C",
        },
    ]
    picked = pick_worked_example(scores)
    assert picked is not None
    assert picked["bioguide_id"] == "B"


def test_separation_n_is_finite_and_monotonic() -> None:
    prior = BetaPrior(alpha=2.0, beta=2.0, source="weakly_informative", n_members=0)
    small = n_needed_to_separate(
        delta_signed=0.80, prior=prior, n_sims=300, max_n=250, seed=1
    )
    large_gap_harder = n_needed_to_separate(
        delta_signed=0.50, prior=prior, n_sims=300, max_n=250, seed=1
    )
    assert small["reached"]
    assert large_gap_harder["reached"]
    assert small["n_needed"] <= large_gap_harder["n_needed"]
    assert small["n_needed"] >= 1
    assert small["power_at_max_n"] is not None


def test_changelog_runs() -> None:
    log = scoring_changelog(limit=10)
    # Empty only if git is unavailable; otherwise Prompt 1/2 commits exist.
    assert isinstance(log, list)
    if log:
        assert {"sha", "date", "subject"} <= set(log[0].keys())


def test_config_surface_for_page() -> None:
    cfg = load_scoring_config()
    assert "PASSAGE" in cfg.include_categories
    assert cfg.eb_fallback_alpha == 2.0
