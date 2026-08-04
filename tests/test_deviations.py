"""Tests for the within-party deviation report (Prompt 9)."""

from __future__ import annotations

from pathlib import Path

import pytest

from vact.analysis.deviations import (
    compute_party_deviations,
    render_deviations_md,
    weighted_median,
)
from vact.analysis.scoring import load_scoring_config, set_valence
from vact.warehouse.connection import connect, ensure_schema

THEME = "FEDERAL_CONTRACTING"

# 4-member Democratic caucus. A/B/C vote the party line (NAY on every scoreable
# vote → anti-axis). D flips v1 and v2 to YEA (pro-axis) — crossing the caucus on
# exactly those two roll calls. E is absent on everything (never a defection).
MEMBERS = [
    ("A0000001", "Ann Alpha", 1),
    ("B0000002", "Ben Bravo", 2),
    ("C0000003", "Cara Charlie", 3),
    ("D0000004", "Dan Delta", 4),
    ("E0000005", "Eve Echo", 5),
]
VOTES = ["h-119-1-1", "h-119-1-2", "h-119-1-3", "h-119-1-4"]


def _position(bio: str, vote_id: str) -> str:
    if bio == "E0000005":
        return "NOT_VOTING"
    if bio == "D0000004":
        return "YEA" if vote_id in ("h-119-1-1", "h-119-1-2") else "NAY"
    return "NAY"


@pytest.fixture()
def caucus(tmp_path: Path) -> Path:
    path = tmp_path / "w.duckdb"
    conn = connect(path)
    ensure_schema(conn)
    for bio, name, district in MEMBERS:
        conn.execute(
            """
            INSERT INTO dim_legislator (
                bioguide_id, full_name, chamber, state, district_2025,
                party, term_start, term_end, first_elected, is_incumbent
            ) VALUES (?, ?, 'House', 'VA', ?, 'D',
                      DATE '2025-01-03', DATE '2027-01-03', 2018, TRUE)
            """,
            [bio, name, district],
        )
    for i, vote_id in enumerate(VOTES, start=1):
        conn.execute(
            """
            INSERT INTO fact_vote (
                vote_id, congress, session, chamber, roll_number, vote_date,
                vote_question, vote_category, source_url
            ) VALUES (?, 119, 1, 'House', ?, DATE '2025-03-01', 'On Passage',
                      'PASSAGE', ?)
            """,
            [vote_id, i, f"http://clerk/{vote_id}"],
        )
        set_valence(conn, vote_id=vote_id, impact_tag=THEME, valence=1, source="HUMAN")
    for _bio, _n, _d in MEMBERS:
        for vote_id in VOTES:
            conn.execute(
                "INSERT INTO fact_member_vote (vote_id, bioguide_id, position) VALUES (?, ?, ?)",
                [vote_id, _bio, _position(_bio, vote_id)],
            )
    conn.close()
    return path


def test_weighted_median_basic() -> None:
    assert weighted_median([(-1.0, 4), (-1.0, 4), (-1.0, 4), (0.0, 4)]) == -1.0
    assert weighted_median([]) == 0.0
    # Weight shifts the median toward the heavier value.
    assert weighted_median([(-1.0, 1), (1.0, 9)]) == 1.0


def test_defector_is_top_with_exactly_two_roll_calls(caucus: Path) -> None:
    conn = connect(caucus)
    try:
        devs = compute_party_deviations(conn, load_scoring_config(), map_version="2021")
    finally:
        conn.close()
    assert devs, "expected at least one deviation"
    top = devs[0]
    assert top.bioguide_id == "D0000004"
    assert top.deviation == pytest.approx(1.0)  # score 0.0 vs caucus baseline -1.0
    assert {d.vote_id for d in top.defection_votes} == {"h-119-1-1", "h-119-1-2"}
    assert all(d.position == "YEA" for d in top.defection_votes)


def test_party_liners_and_absentee_do_not_appear(caucus: Path) -> None:
    conn = connect(caucus)
    try:
        devs = compute_party_deviations(conn, load_scoring_config(), map_version="2021")
    finally:
        conn.close()
    reported = {d.bioguide_id for d in devs}
    # A/B/C never cross the caucus; E only has absences → none qualify.
    assert reported == {"D0000004"}
    assert "E0000005" not in reported


def test_absences_are_not_defections(caucus: Path) -> None:
    """E votes on nothing; must never be flagged as a defector."""
    conn = connect(caucus)
    try:
        devs = compute_party_deviations(conn, load_scoring_config(), map_version="2021")
    finally:
        conn.close()
    assert all(d.bioguide_id != "E0000005" for d in devs)


def test_defection_votes_link_to_source(caucus: Path) -> None:
    conn = connect(caucus)
    try:
        devs = compute_party_deviations(conn, load_scoring_config(), map_version="2021")
        md = render_deviations_md(devs, load_scoring_config())
    finally:
        conn.close()
    assert "http://clerk/h-119-1-1" in md
    assert "Dan Delta" in md


def test_empty_when_no_defections(tmp_path: Path) -> None:
    """A perfectly party-line caucus produces no deviations."""
    path = tmp_path / "w.duckdb"
    conn = connect(path)
    ensure_schema(conn)
    for bio, name, district in MEMBERS[:4]:
        conn.execute(
            """
            INSERT INTO dim_legislator (
                bioguide_id, full_name, chamber, state, district_2025,
                party, term_start, term_end, first_elected, is_incumbent
            ) VALUES (?, ?, 'House', 'VA', ?, 'D',
                      DATE '2025-01-03', DATE '2027-01-03', 2018, TRUE)
            """,
            [bio, name, district],
        )
    for i, vote_id in enumerate(VOTES, start=1):
        conn.execute(
            "INSERT INTO fact_vote (vote_id, congress, session, chamber, roll_number, "
            "vote_date, vote_question, vote_category) VALUES (?, 119, 1, 'House', ?, "
            "DATE '2025-03-01', 'On Passage', 'PASSAGE')",
            [vote_id, i],
        )
        set_valence(conn, vote_id=vote_id, impact_tag=THEME, valence=1, source="HUMAN")
        for bio, _n, _d in MEMBERS[:4]:
            conn.execute(
                "INSERT INTO fact_member_vote (vote_id, bioguide_id, position) "
                "VALUES (?, ?, 'NAY')",
                [vote_id, bio],
            )
    try:
        devs = compute_party_deviations(conn, load_scoring_config(), map_version="2021")
    finally:
        conn.close()
    assert devs == []
