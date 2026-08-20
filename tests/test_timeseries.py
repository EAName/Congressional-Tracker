"""Tests for expanding-window EB series (Prompt 5)."""

from __future__ import annotations

from datetime import date

from vact.analysis.estimators import attach_empirical_bayes
from vact.analysis.scoring import ScoringConfig, frame_from_vote_rows
from vact.analysis.timeseries import expanding_series
from vact.analysis.votes import VoteRow


def _cfg(**kwargs: object) -> ScoringConfig:
    base: dict[str, object] = {
        "version": 1,
        "axis_name": "axis",
        "axis_description": "",
        "include_categories": frozenset({"PASSAGE"}),
        "exclude_categories": frozenset(),
        "min_contested": 3,
        "wilson_z": 1.96,
        "min_eligible_for_display": 3,
        "eb_min_caucus": 3,
        "ts_window_days": 90,
    }
    base.update(kwargs)
    return ScoringConfig(**base)  # type: ignore[arg-type]


def _row(
    *,
    bio: str,
    name: str,
    party: str,
    theme: str,
    day: str,
    roll: str,
    direction: str = "advance",
    cast: str = "yea",
    district: str = "1",
) -> VoteRow:
    return VoteRow.model_validate(
        {
            "member_bioguide_id": bio,
            "member_name": name,
            "district": district,
            "party": party,
            "congress": 119,
            "chamber": "House",
            "rollcall_id": roll,
            "rollcall_date": day,
            "bill_id": f"hr-{roll}",
            "theme": theme,
            "axis_direction": direction,
            "vote_cast": cast,
            "contested": True,
            "adjudicator": "HUMAN",
            "source_url": "https://example.test/v",
        }
    )


def test_credible_band_narrows_as_n_grows() -> None:
    """Frozen weakly-informative prior: width is monotone in n."""
    cfg = _cfg(eb_min_caucus=99)
    rows = [
        _row(bio="A", name="A", party="Democrat", theme="T", day=f"2026-01-0{i}", roll=f"h-{i}", cast="yea")
        for i in range(1, 6)
    ]
    payload = expanding_series(rows, cfg)
    pts = payload["series"][0]["points"]
    widths = [p["hi"] - p["lo"] for p in pts]
    ns = [p["n"] for p in pts]
    assert ns == [1, 2, 3, 4, 5]
    assert all(a >= b - 1e-9 for a, b in zip(widths, widths[1:]))
    assert widths[-1] < widths[0]


def test_last_point_matches_snapshot_estimator() -> None:
    cfg = _cfg()
    rows: list[VoteRow] = []
    for i, bio in enumerate(["A", "B", "C", "D"], start=1):
        for d in range(1, 5):
            rows.append(
                _row(
                    bio=bio,
                    name=bio,
                    party="Democrat",
                    theme="T",
                    day=f"2026-02-0{d}",
                    roll=f"h-{bio}-{d}",
                    cast="yea" if i < 4 or d < 3 else "nay",
                )
            )
    payload = expanding_series(rows, cfg)
    frame, _ = attach_empirical_bayes(frame_from_vote_rows(rows, cfg), cfg)
    by_bio = {r["bioguide_id"]: r for r in frame}
    for cell in payload["series"]:
        last = cell["points"][-1]
        snap = by_bio[cell["bioguide_id"]]
        assert last["n"] == snap["n"]
        assert last["k"] == snap["k"]
        assert last["eb"] == snap["eb_score"]
        assert last["lo"] == snap["cred_lo"]
        assert last["hi"] == snap["cred_hi"]


def test_n_is_nondecreasing() -> None:
    cfg = _cfg()
    rows = [
        _row(bio="A", name="A", party="Republican", theme="T", day="2026-03-01", roll="h-1"),
        _row(bio="A", name="A", party="Republican", theme="T", day="2026-03-02", roll="h-2"),
        _row(bio="A", name="A", party="Republican", theme="T", day="2026-03-02", roll="h-3"),
        _row(bio="B", name="B", party="Republican", theme="T", day="2026-03-01", roll="h-1"),
        _row(bio="B", name="B", party="Republican", theme="T", day="2026-03-02", roll="h-2"),
    ]
    pts = expanding_series(rows, cfg)["series"]
    a = next(s for s in pts if s["bioguide_id"] == "A")["points"]
    assert [p["n"] for p in a] == [1, 3]


def test_biggest_mover_picks_the_window_shift() -> None:
    cfg = _cfg(min_contested=3, ts_window_days=90)
    rows: list[VoteRow] = []
    # Stable member: four yeas in January, nothing later.
    for d in range(1, 5):
        rows.append(
            _row(bio="S", name="Stable", party="Democrat", theme="T", day=f"2026-01-0{d}", roll=f"s-{d}")
        )
    # Mover: three nays in January, three yeas in May (inside 90d of as_of June 1).
    for d in range(1, 4):
        rows.append(
            _row(
                bio="M",
                name="Mover",
                party="Democrat",
                theme="T",
                day=f"2026-01-1{d}",
                roll=f"m-early-{d}",
                cast="nay",
            )
        )
        rows.append(
            _row(
                bio="M",
                name="Mover",
                party="Democrat",
                theme="T",
                day=f"2026-05-0{d}",
                roll=f"m-late-{d}",
                cast="yea",
            )
        )
    payload = expanding_series(rows, cfg, as_of=date(2026, 6, 1))
    mover = payload["biggest_mover"]
    assert mover is not None
    assert mover["bioguide_id"] == "M"
    assert mover["delta"] > 0
    assert mover["window_days"] == 90
    assert payload["as_of"] == "2026-06-01"
