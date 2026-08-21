"""Generic-ballot poll average (primary-poll archive only)."""

from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path

import pytest

from vact.analysis.poll_average import (
    PollArchiveError,
    build_generic_ballot,
    environment_support,
    estimate_house_effects,
    firm_influence_pp,
    single_poll_influence_pp,
    latest_two_party,
    load_config,
    load_polls,
    trend_series,
)

FIELDS = [
    "pollster", "sponsor", "start_date", "end_date", "n",
    "population", "dem", "rep", "partisan", "source_url",
]


def _write(path: Path, rows: list[dict]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({**{k: "" for k in FIELDS}, **r})
    return path


def _poll(pollster, day, dem, rep, n=1000, population="lv"):
    return {
        "pollster": pollster, "start_date": day.isoformat(), "end_date": day.isoformat(),
        "n": n, "population": population, "dem": dem, "rep": rep,
        "source_url": "https://example.invalid/poll",
    }


def test_empty_archive_publishes_nothing(tmp_path: Path) -> None:
    doc = build_generic_ballot(polls_path=_write(tmp_path / "p.csv", []))
    assert doc["n_polls"] == 0
    assert doc["current"] is None
    assert doc["series"] == []
    assert "required before" in doc["status"]


def test_below_min_polls_publishes_nothing(tmp_path: Path) -> None:
    day = date(2026, 8, 1)
    rows = [_poll("A", day, 48, 45), _poll("B", day, 47, 46)]
    doc = build_generic_ballot(polls_path=_write(tmp_path / "p.csv", rows))
    assert doc["n_polls"] == 2
    assert doc["current"] is None


def test_trend_recovers_a_flat_signal(tmp_path: Path) -> None:
    base = date(2026, 6, 1)
    rows = [_poll(f"P{i}", base + timedelta(days=i * 3), 52, 48) for i in range(12)]
    path = _write(tmp_path / "p.csv", rows)
    doc = build_generic_ballot(polls_path=path, as_of=base + timedelta(days=33))
    assert doc["current"] is not None
    # Every poll is D 52 / R 48 -> two-party 0.52, minus the LV offset of 0.
    assert doc["current"]["dem_two_party"] == pytest.approx(0.52, abs=0.005)
    assert doc["current"]["margin_pp"] == pytest.approx(4.0, abs=0.6)


def test_band_is_wider_when_polls_disagree(tmp_path: Path) -> None:
    base = date(2026, 6, 1)
    tight = [_poll(f"T{i}", base + timedelta(days=i), 51, 49) for i in range(10)]
    spread = [
        _poll(f"S{i}", base + timedelta(days=i), 45 + (10 if i % 2 else 0), 49)
        for i in range(10)
    ]
    d_tight = build_generic_ballot(polls_path=_write(tmp_path / "t.csv", tight))
    d_spread = build_generic_ballot(polls_path=_write(tmp_path / "s.csv", spread))
    width = lambda d: d["current"]["hi"] - d["current"]["lo"]  # noqa: E731
    assert width(d_spread) > width(d_tight)


def test_house_effect_is_detected_and_shrunk(tmp_path: Path) -> None:
    """A firm consistently 6pp more Democratic than everyone else gets a positive
    house effect, but shrinkage keeps it below the raw gap."""
    base = date(2026, 6, 1)
    rows = []
    for i in range(14):
        day = base + timedelta(days=i * 2)
        rows.append(_poll(f"Neutral{i}", day, 50, 50))
    for i in range(6):
        rows.append(_poll("Leaner", base + timedelta(days=i * 4), 56, 44))
    polls = load_polls(_write(tmp_path / "p.csv", rows))
    effects = estimate_house_effects(polls, load_config())
    assert effects["Leaner"] > 0.01
    assert effects["Leaner"] < 0.06  # shrunk, and clamped by max_abs


def test_single_poll_firm_is_shrunk_hard(tmp_path: Path) -> None:
    base = date(2026, 6, 1)
    rows = [_poll(f"N{i}", base + timedelta(days=i), 50, 50) for i in range(12)]
    rows.append(_poll("OneOff", base + timedelta(days=5), 60, 40))
    polls = load_polls(_write(tmp_path / "p.csv", rows))
    effects = estimate_house_effects(polls, load_config())
    # Raw residual is ~10pp; one poll keeps 1/(1+4) of it at most.
    assert 0 < effects["OneOff"] < 0.035


def test_prolific_pollster_cannot_dominate(tmp_path: Path) -> None:
    base = date(2026, 7, 1)
    rows = [_poll("Daily", base + timedelta(days=i), 40, 60, n=800) for i in range(30)]
    rows += [_poll(f"Rare{i}", base + timedelta(days=i * 10), 55, 45, n=800) for i in range(3)]
    doc = build_generic_ballot(polls_path=_write(tmp_path / "p.csv", rows))
    # 30 polls vs 3, same sample size: without the frequency penalty the trend
    # would sit on top of Daily's 0.40.
    assert doc["current"]["dem_two_party"] > 0.42


def test_sample_type_offsets_move_rv_toward_lv(tmp_path: Path) -> None:
    base = date(2026, 6, 1)
    lv = [_poll(f"L{i}", base + timedelta(days=i), 52, 48, population="lv") for i in range(8)]
    rv = [_poll(f"R{i}", base + timedelta(days=i), 52, 48, population="rv") for i in range(8)]
    d_lv = build_generic_ballot(polls_path=_write(tmp_path / "l.csv", lv))
    d_rv = build_generic_ballot(polls_path=_write(tmp_path / "r.csv", rv))
    assert d_rv["current"]["dem_two_party"] < d_lv["current"]["dem_two_party"]


def test_bad_population_rejected(tmp_path: Path) -> None:
    rows = [_poll("A", date(2026, 6, 1), 50, 50)]
    rows[0]["population"] = "voters"
    with pytest.raises(PollArchiveError, match="population"):
        load_polls(_write(tmp_path / "p.csv", rows))


def test_end_before_start_rejected(tmp_path: Path) -> None:
    rows = [_poll("A", date(2026, 6, 1), 50, 50)]
    rows[0]["end_date"] = "2026-05-01"
    with pytest.raises(PollArchiveError, match="before start_date"):
        load_polls(_write(tmp_path / "p.csv", rows))


def test_committed_archive_is_loadable_and_sourced() -> None:
    """Every archive row must carry a source URL; provenance is the whole point
    of collecting primary polls rather than ingesting an aggregator."""
    polls = load_polls()
    assert isinstance(polls, list)
    for poll in polls:
        assert poll.source_url.startswith("http"), f"{poll.pollster} has no source"
        assert poll.n > 0
        assert 0.2 < poll.dem_two_party < 0.8


def test_band_does_not_collapse_on_a_lone_poll(tmp_path: Path) -> None:
    """A thin archive lets one poll dominate the local kernel. Without a sampling
    floor the band would claim near-certainty from a single survey."""
    base = date(2026, 6, 1)
    rows = [
        _poll("A", base, 52, 48, n=1000),
        _poll("B", base + timedelta(days=120), 52, 48, n=1000),
        _poll("C", base + timedelta(days=240), 52, 48, n=1000),
    ]
    doc = build_generic_ballot(polls_path=_write(tmp_path / "p.csv", rows),
                               as_of=base + timedelta(days=240))
    pt = doc["series"][-1]
    assert pt["effective_n_polls"] < 1.5, "expected one poll to dominate here"
    width = pt["hi"] - pt["lo"]
    # sqrt(.5*.5/1000) ~= .0158; a 90% band is ~2z of that at minimum
    assert width > 0.04, f"band collapsed to {width:.4f}"


def test_sampling_floor_scales_with_sample_size(tmp_path: Path) -> None:
    base = date(2026, 6, 1)
    small = [_poll(f"S{i}", base + timedelta(days=i * 90), 52, 48, n=400) for i in range(3)]
    big = [_poll(f"B{i}", base + timedelta(days=i * 90), 52, 48, n=4000) for i in range(3)]
    ds = build_generic_ballot(polls_path=_write(tmp_path / "s.csv", small))
    db = build_generic_ballot(polls_path=_write(tmp_path / "b.csv", big))
    w = lambda d: d["series"][-1]["hi"] - d["series"][-1]["lo"]  # noqa: E731
    assert w(ds) > w(db)


def test_one_wild_poll_holds_the_gate_shut(tmp_path: Path) -> None:
    """An archive where a single survey swings the average must not drive the
    seat forecasts, however many polls it nominally contains."""
    base = date(2026, 8, 1)
    rows = [_poll(f"P{i}", base - timedelta(days=i * 40), 50, 50) for i in range(9)]
    rows.append(_poll("Outlier", base, 70, 30, n=3000))
    path = _write(tmp_path / "p.csv", rows)
    doc = build_generic_ballot(polls_path=path, as_of=base)
    assert doc["current"] is not None, "the chart still renders"
    gate = environment_support(doc, polls=load_polls(path))
    assert gate["ok"] is False
    assert gate["single_poll_influence_pp"] > 1.0
    assert latest_two_party(polls_path=path, as_of=base) is None


def test_stable_archive_opens_the_gate(tmp_path: Path) -> None:
    base = date(2026, 6, 1)
    rows = [_poll(f"P{i}", base + timedelta(days=i * 2), 52, 48) for i in range(24)]
    path = _write(tmp_path / "p.csv", rows)
    doc = build_generic_ballot(polls_path=path, as_of=base + timedelta(days=46))
    gate = environment_support(doc, polls=load_polls(path))
    assert gate["ok"] is True, gate["reasons"]
    assert gate["single_poll_influence_pp"] < 1.0
    env = latest_two_party(polls_path=path, as_of=base + timedelta(days=46))
    assert env is not None
    assert env["dem_two_party"] == pytest.approx(0.52, abs=0.01)


def test_influence_falls_as_the_archive_deepens(tmp_path: Path) -> None:
    """The gate has to be a measure of stability, not a poll counter. With real
    scatter between firms, each additional poll buys less leverage for any one
    of them."""
    base = date(2026, 8, 1)
    # deterministic scatter around 52/48, a few points either way
    scatter = [0, 3, -3, 2, -2, 4, -4, 1, -1, 3, -3, 2, -2, 5, -5, 1, -1, 0, 2, -2]

    def influence(k: int) -> float:
        rows = [
            _poll(f"P{i}", base - timedelta(days=i * 2), 52 + scatter[i], 48 - scatter[i])
            for i in range(k)
        ]
        return single_poll_influence_pp(
            load_polls(_write(tmp_path / f"{k}.csv", rows)), as_of=base
        )

    few, many = influence(5), influence(20)
    assert many < few, f"20 polls ({many:.3f}) should be steadier than 5 ({few:.3f})"


def test_committed_archive_is_stable_enough_to_publish() -> None:
    """Guards the live archive: if it degrades, this fails rather than quietly
    feeding a shaky environment into every race forecast."""
    doc = build_generic_ballot()
    gate = doc["environment_gate"]
    assert gate["single_poll_influence_pp"] is not None
    assert gate["ok"], gate["reasons"]


def test_committed_archive_gate_state_is_reported() -> None:
    doc = build_generic_ballot()
    assert "environment_gate" in doc
    assert isinstance(doc["environment_gate"]["reasons"], list)


def test_a_lopsided_new_firm_closes_the_gate(tmp_path: Path) -> None:
    """Five polls from one house-leaning entrant must not quietly reset the
    national environment. Measured at 2.0 points of firm influence."""
    base = date(2026, 8, 16)
    steady = [_poll(f"S{i}", base - timedelta(days=i * 20), 48, 44) for i in range(10)]
    lean = [_poll("LeanShop", base - timedelta(days=d), 54, 40) for d in (2, 5, 8, 11, 14)]
    path = _write(tmp_path / "p.csv", steady + lean)
    polls = load_polls(path)
    inf, who = firm_influence_pp(polls, as_of=base)
    assert who == "LeanShop"
    assert inf > 1.5
    doc = build_generic_ballot(polls_path=path, as_of=base)
    assert environment_support(doc, polls=polls)["ok"] is False


def test_firm_influence_catches_what_poll_influence_misses(tmp_path: Path) -> None:
    """The frequency penalty makes each survey from a prolific firm look
    uninfluential. Dropping the firm is the question that actually matters."""
    base = date(2026, 8, 16)
    others = [_poll(f"O{i}", base - timedelta(days=i * 25), 48, 44) for i in range(6)]
    prolific = [_poll("Prolific", base - timedelta(days=d), 55, 39) for d in range(1, 13, 2)]
    polls = load_polls(_write(tmp_path / "p.csv", others + prolific))
    per_poll = single_poll_influence_pp(polls, as_of=base)
    per_firm, who = firm_influence_pp(polls, as_of=base)
    assert who == "Prolific"
    assert per_firm > per_poll, (
        f"firm-level {per_firm:.2f} should exceed poll-level {per_poll:.2f} "
        "when one firm carries the estimate"
    )


def test_committed_archive_firm_influence_is_reported() -> None:
    gate = build_generic_ballot()["environment_gate"]
    assert gate["firm_influence_pp"] is not None
    assert gate["n_firms"] >= 3
