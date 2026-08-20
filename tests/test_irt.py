"""Tests for 2PL IRT (Prompt 4). MCMC tests skip if pymc is not installed."""

from __future__ import annotations

import numpy as np
import pytest

from vact.analysis.irt_pipeline import (
    IrtConfig,
    apply_anchor_sign,
    build_response_matrix,
    load_irt_config,
)
from vact.analysis.votes import VoteRow


def _cfg(**kwargs: object) -> IrtConfig:
    base = load_irt_config()
    data = {**base.__dict__, **kwargs}
    return IrtConfig(**data)


def _row(bio: str, vote: str, cast: str, theme: str = "T", party: str = "Democrat") -> VoteRow:
    return VoteRow.model_validate(
        {
            "member_bioguide_id": bio,
            "member_name": bio,
            "district": "1",
            "party": party,
            "congress": 119,
            "chamber": "House",
            "rollcall_id": vote,
            "rollcall_date": "2026-01-01",
            "bill_id": vote,
            "theme": theme,
            "axis_direction": "advance",
            "vote_cast": cast,
            "contested": True,
            "adjudicator": "HUMAN",
            "source_url": "https://example.test/v",
        }
    )


def test_config_anchors_are_bioguides() -> None:
    cfg = load_irt_config()
    assert cfg.low_anchor[0].isalpha()
    assert cfg.low_anchor != cfg.high_anchor
    assert cfg.chains == 4


def test_theme_dedup_keeps_one_response() -> None:
    rows = [
        _row("A", "h-1", "yea", theme="T1"),
        _row("A", "h-1", "yea", theme="T2"),
        _row("B", "h-1", "nay"),
        _row("C", "h-1", "yea"),
        _row("A", "h-2", "nay"),
        _row("B", "h-2", "yea"),
        _row("C", "h-2", "nay"),
        _row("A", "h-3", "yea"),
        _row("B", "h-3", "nay"),
        _row("C", "h-3", "yea"),
    ]
    matrix = build_response_matrix(rows, _cfg(min_member_votes=2, min_item_voters=2))
    assert int(matrix.y.size) == 9
    themes = next(i["themes"] for i in matrix.items if i["vote_id"] == "h-1")
    assert "T1" in themes and "T2" in themes


def test_unanimous_items_dropped() -> None:
    rows = []
    for bio in "ABC":
        rows.append(_row(bio, "all-yea", "yea"))
        rows.append(_row(bio, "split", "yea" if bio != "C" else "nay"))
        rows.append(_row(bio, "split2", "nay" if bio != "A" else "yea"))
    matrix = build_response_matrix(rows, _cfg(min_member_votes=2, min_item_voters=2))
    assert "all-yea" not in matrix.item_ids
    assert "split" in matrix.item_ids


def test_anchor_sign_flip_is_per_draw() -> None:
    rng = np.random.default_rng(0)
    theta = rng.normal(size=(200, 4))
    b = rng.normal(size=(200, 3))
    gamma = rng.normal(size=(200, 3))
    i_low, i_high = 0, 3
    t2, b2, g2 = apply_anchor_sign(theta, b, gamma, i_low, i_high)
    assert np.all(t2[:, i_high] >= t2[:, i_low] - 1e-12)
    flipped = theta[:, i_high] < theta[:, i_low]
    np.testing.assert_allclose(t2[flipped], -theta[flipped])
    np.testing.assert_allclose(b2[flipped], -b[flipped])
    np.testing.assert_allclose(g2[flipped], -gamma[flipped])


def _simulate(n_m: int = 15, n_j: int = 40, seed: int = 1):
    rng = np.random.default_rng(seed)
    theta = np.linspace(-2.0, 2.0, n_m)
    b = rng.normal(0, 0.8, n_j)
    gamma = np.abs(rng.normal(1.2, 0.25, n_j))
    p = 1.0 / (1.0 + np.exp(-gamma * (theta[:, None] - b)))
    y = rng.binomial(1, p)
    bios = tuple(f"M{i:02d}" for i in range(n_m))
    items = tuple(f"V{j:02d}" for j in range(n_j))
    rows = []
    for i, bio in enumerate(bios):
        party = "Democrat" if theta[i] < 0 else "Republican"
        for j, vid in enumerate(items):
            rows.append(_row(bio, vid, "yea" if y[i, j] else "nay", party=party))
    return theta, bios, rows


@pytest.mark.irt
def test_synthetic_recovery_and_anchor_sign() -> None:
    pytest.importorskip("pymc")
    from vact.analysis.irt_pipeline import _stack_draws, fit_2pl

    theta_true, bios, rows = _simulate()
    cfg = _cfg(
        low_anchor=bios[0],
        high_anchor=bios[-1],
        draws=400,
        tune=400,
        rhat_max=1.05,
        ess_bulk_min=80,
        min_member_votes=5,
        min_item_voters=5,
    )
    matrix = build_response_matrix(rows, cfg)
    idata = fit_2pl(matrix, cfg, progressbar=False)
    hat = _stack_draws(idata.posterior["theta"]).mean(axis=0)
    true_ord = np.array([theta_true[bios.index(b)] for b in matrix.member_ids])
    corr = float(np.corrcoef(true_ord, hat)[0, 1])
    assert corr > 0.8
    i_low = matrix.member_ids.index(bios[0])
    i_high = matrix.member_ids.index(bios[-1])
    assert hat[i_high] > hat[i_low]


@pytest.mark.irt
def test_anchor_sign_stable_across_seeds() -> None:
    pytest.importorskip("pymc")
    from vact.analysis.irt_pipeline import _stack_draws, fit_2pl

    _, bios, rows = _simulate(seed=2)
    signs = []
    for seed in (11, 23):
        cfg = _cfg(
            low_anchor=bios[0],
            high_anchor=bios[-1],
            draws=300,
            tune=300,
            seed=seed,
            rhat_max=1.08,
            ess_bulk_min=50,
            min_member_votes=5,
            min_item_voters=5,
        )
        matrix = build_response_matrix(rows, cfg)
        idata = fit_2pl(matrix, cfg, seed=seed, progressbar=False)
        hat = _stack_draws(idata.posterior["theta"]).mean(axis=0)
        i_low = matrix.member_ids.index(bios[0])
        i_high = matrix.member_ids.index(bios[-1])
        signs.append(np.sign(hat[i_high] - hat[i_low]))
    assert signs[0] == signs[1] == 1.0
