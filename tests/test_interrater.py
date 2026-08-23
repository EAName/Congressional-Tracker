"""Inter-rater reliability tooling."""

from __future__ import annotations

from vact.analysis.interrater import Agreement, compare, draw_sample


def _units(n: int) -> list[dict[str, str]]:
    return [
        {"vote_id": f"h-119-1-{i}", "impact_tag": "INPUT_COSTS", "vote_date": "2025-01-01",
         "bill_id": f"hr-{i}-119", "title": f"Bill {i}", "crs_lead": ""}
        for i in range(n)
    ]


def test_sample_never_leaks_the_first_coder_call() -> None:
    """The whole point is a blind second read. A leaked valence makes the
    agreement rate meaningless."""
    rows = draw_sample(_units(30), n=10)
    assert len(rows) == 10
    assert all(r["valence"] == "" for r in rows)
    assert all("axis_direction" not in r and "party" not in r for r in rows)


def test_draw_is_deterministic_for_a_seed() -> None:
    """A reproducible draw is auditable; an unlogged random one invites
    'you sampled the agreeable ones'."""
    a = [r["vote_id"] for r in draw_sample(_units(40), n=8, seed="x")]
    b = [r["vote_id"] for r in draw_sample(_units(40), n=8, seed="x")]
    c = [r["vote_id"] for r in draw_sample(_units(40), n=8, seed="y")]
    assert a == b
    assert a != c


def test_agreement_and_disagreements_are_reported() -> None:
    sample = [
        {"vote_id": "v1", "impact_tag": "T", "title": "one", "valence": "1"},
        {"vote_id": "v2", "impact_tag": "T", "title": "two", "valence": "-1"},
        {"vote_id": "v3", "impact_tag": "T", "title": "three", "valence": "1"},
    ]
    adjudicated = {("v1", "T"): 1, ("v2", "T"): 1, ("v3", "T"): 1}
    agree, kappa = compare(sample, adjudicated)
    assert agree.n == 3
    assert agree.agreed == 2
    assert agree.rate == 2 / 3
    assert [d["vote_id"] for d in agree.disagreements] == ["v2"]


def test_kappa_punishes_a_coder_who_marks_everything_the_same() -> None:
    """Raw agreement flatters a blanket call — which is exactly the criticism a
    hostile reader will make. Kappa is chance-corrected, so it does not."""
    a = Agreement(n=0, agreed=0, disagreements=[])
    same = [1] * 20
    assert a.cohen_kappa(same, same) is None  # no variance -> undefined, not 1.0
    mixed_first = [1] * 15 + [-1] * 5
    mixed_second = [1] * 14 + [-1] * 6
    k = a.cohen_kappa(mixed_first, mixed_second)
    assert k is not None and 0.0 < k < 1.0


def test_unfilled_rows_are_ignored_not_defaulted() -> None:
    sample = [
        {"vote_id": "v1", "impact_tag": "T", "title": "", "valence": ""},
        {"vote_id": "v2", "impact_tag": "T", "title": "", "valence": "1"},
    ]
    agree, _ = compare(sample, {("v1", "T"): 1, ("v2", "T"): 1})
    assert agree.n == 1
