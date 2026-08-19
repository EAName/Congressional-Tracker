"""Tests for the base-pack signed scoring frame (valence, scoreable filter, math)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from vact.analysis.scoring import (
    ScoringConfig,
    build_scores_frame,
    load_scoring_config,
    load_valence,
    propose_valence,
    scoreable_pairs,
    set_valence,
    signed_score_from_counts,
    wilson_interval,
)
from vact.warehouse.connection import connect, ensure_schema

# --------------------------------------------------------------------------- #
# Synthetic caucus fixture
#
# One theme (FEDERAL_CONTRACTING), five scoreable PASSAGE votes (valence +1),
# plus a CLOTURE vote and an un-adjudicated PASSAGE vote that must both be
# excluded. Members A/B/C vote the party line (YEA on everything); member D
# flips v1 and v2 to NAY and is absent (NOT_VOTING) on v5.
# --------------------------------------------------------------------------- #
MEMBERS = [
    ("A0000001", "Ann Alpha", 1),
    ("B0000002", "Ben Bravo", 2),
    ("C0000003", "Cara Charlie", 3),
    ("D0000004", "Dan Delta", 4),
]

# vote_id, category, has_valence
VOTES = [
    ("h-119-1-1", "PASSAGE", True),
    ("h-119-1-2", "PASSAGE", True),
    ("h-119-1-3", "PASSAGE", True),
    ("h-119-1-4", "PASSAGE", True),
    ("h-119-1-5", "PASSAGE", True),  # absence test
    ("h-119-1-9", "CLOTURE", True),  # excluded: procedural category
    ("h-119-1-8", "PASSAGE", False),  # excluded: no adjudicated valence
]


def _positions() -> list[tuple[str, str, str]]:
    """(vote_id, bioguide_id, position) rows for every member × vote."""
    rows: list[tuple[str, str, str]] = []
    for vote_id, _cat, _v in VOTES:
        for bio, _name, _d in MEMBERS:
            if bio == "D0000004":
                if vote_id in ("h-119-1-1", "h-119-1-2"):
                    pos = "NAY"
                elif vote_id == "h-119-1-5":
                    pos = "NOT_VOTING"
                elif vote_id == "h-119-1-8":
                    pos = "NAY"
                else:
                    pos = "YEA"
            else:
                pos = "YEA"
            rows.append((vote_id, bio, pos))
    return rows


def seed_scoring_warehouse(path: Path) -> Path:
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

    for i, (vote_id, category, _v) in enumerate(VOTES, start=1):
        conn.execute(
            """
            INSERT INTO fact_vote (
                vote_id, congress, session, chamber, roll_number, vote_date,
                vote_question, vote_type, vote_category, result, passed, bill_id,
                yea_total, nay_total, present_total, not_voting_total, source_url
            ) VALUES (?, 119, 1, 'House', ?, DATE '2025-03-01',
                      'On Passage', 'YEA-AND-NAY', ?, 'Passed', TRUE, NULL,
                      3, 1, 0, 0, ?)
            """,
            [vote_id, i, category, f"http://clerk/{vote_id}"],
        )

    for vote_id, bio, pos in _positions():
        conn.execute(
            "INSERT INTO fact_member_vote (vote_id, bioguide_id, position) VALUES (?, ?, ?)",
            [vote_id, bio, pos],
        )

    # Adjudicated valence: +1 on every scoreable vote that "has_valence", INCLUDING
    # the cloture vote (to prove the category filter — not just missing valence —
    # is what excludes procedural votes).
    for vote_id, _cat, has_valence in VOTES:
        if has_valence:
            set_valence(
                conn,
                vote_id=vote_id,
                impact_tag="FEDERAL_CONTRACTING",
                valence=1,
                source="HUMAN",
            )

    conn.close()
    return path


@pytest.fixture()
def warehouse(tmp_path: Path) -> Path:
    return seed_scoring_warehouse(tmp_path / "warehouse.duckdb")


# --------------------------------------------------------------------------- #
# Wilson + signed-score math (pure)
# --------------------------------------------------------------------------- #
def test_wilson_interval_brackets_proportion() -> None:
    low, high = wilson_interval(8, 10, 1.96)
    assert 0.0 <= low < 0.8 < high <= 1.0
    # Known Wilson values for 8/10 at z=1.96 (~0.49, ~0.94).
    assert low == pytest.approx(0.490, abs=0.01)
    assert high == pytest.approx(0.943, abs=0.01)


def test_wilson_zero_n_is_maximally_uncertain() -> None:
    assert wilson_interval(0, 0, 1.96) == (0.0, 1.0)


def test_signed_score_all_pro_is_plus_one() -> None:
    out = signed_score_from_counts(4, 4, 1.96)
    assert out["signed_score"] == 1.0
    assert out["wilson_high"] == pytest.approx(1.0, abs=1e-9)
    assert out["wilson_low"] < 1.0  # band is never a point


def test_signed_score_half_pro_is_zero() -> None:
    out = signed_score_from_counts(2, 4, 1.96)
    assert out["signed_score"] == 0.0
    assert out["wilson_low"] < 0.0 < out["wilson_high"]


def test_signed_score_no_contested_is_none() -> None:
    out = signed_score_from_counts(0, 0, 1.96)
    assert out["signed_score"] is None


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
def test_shipped_config_loads() -> None:
    cfg = load_scoring_config()
    assert "PASSAGE" in cfg.include_categories
    assert "CLOTURE" in cfg.exclude_categories
    assert cfg.min_contested >= 1
    assert cfg.wilson_z > 0


def test_config_rejects_category_in_both_lists(tmp_path: Path) -> None:
    bad = tmp_path / "scoring.yaml"
    bad.write_text(
        "scoreable:\n"
        "  include_categories: [PASSAGE]\n"
        "  exclude_categories: [PASSAGE]\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="both include and exclude"):
        load_scoring_config(bad)


# --------------------------------------------------------------------------- #
# Scoreable filter
# --------------------------------------------------------------------------- #
def test_scoreable_filter_excludes_procedural_and_unadjudicated(warehouse: Path) -> None:
    conn = connect(warehouse)
    try:
        pairs = scoreable_pairs(conn, load_scoring_config())
    finally:
        conn.close()
    vote_ids = {p["vote_id"] for p in pairs}
    assert vote_ids == {"h-119-1-1", "h-119-1-2", "h-119-1-3", "h-119-1-4", "h-119-1-5"}
    assert "h-119-1-9" not in vote_ids  # cloture excluded despite having valence
    assert "h-119-1-8" not in vote_ids  # no valence row


# --------------------------------------------------------------------------- #
# The frame
# --------------------------------------------------------------------------- #
def _by_bio(frame: list[dict], tag: str = "FEDERAL_CONTRACTING") -> dict[str, dict]:
    return {r["bioguide_id"]: r for r in frame if r["impact_tag"] == tag}


def test_frame_party_liners_score_plus_one(warehouse: Path) -> None:
    conn = connect(warehouse)
    try:
        frame = build_scores_frame(conn, map_version="2021")
    finally:
        conn.close()
    rows = _by_bio(frame)
    for bio in ("A0000001", "B0000002", "C0000003"):
        r = rows[bio]
        assert r["signed_score"] == 1.0
        assert (r["n_yea"], r["n_nay"]) == (5, 0)
        assert r["n_contested"] == 5
        assert r["absence_rate"] == 0.0


def test_frame_defector_scores_zero_with_absence_tracked(warehouse: Path) -> None:
    conn = connect(warehouse)
    try:
        frame = build_scores_frame(conn, map_version="2021")
    finally:
        conn.close()
    d = _by_bio(frame)["D0000004"]
    assert d["n_contested"] == 4  # v1..v4; v5 is NOT_VOTING, not contested
    assert (d["n_yea"], d["n_nay"]) == (2, 2)
    assert d["n_pro"] == 2
    assert d["signed_score"] == 0.0
    assert d["n_not_voting"] == 1
    assert d["absence_rate"] == pytest.approx(0.2)  # 1 of 5 eligible
    assert d["sufficient"] is True  # 4 >= default min_contested (3)


def test_frame_absence_is_never_an_anti_axis_vote(warehouse: Path) -> None:
    """A NOT_VOTING must not lower the pro count nor count as contested."""
    conn = connect(warehouse)
    try:
        frame = build_scores_frame(conn, map_version="2021")
    finally:
        conn.close()
    d = _by_bio(frame)["D0000004"]
    # If the absence were mis-counted as NAY, n_contested would be 5 and score < 0.
    assert d["n_contested"] == 4
    assert d["signed_score"] == 0.0


def test_rule_resolution_excluded_even_with_valence_and_tag(tmp_path: Path) -> None:
    """A 'Providing for consideration' hres vote is procedural — never scoreable,
    even though it lands in vote_category PASSAGE and carries an inherited tag."""
    path = tmp_path / "w.duckdb"
    conn = connect(path)
    ensure_schema(conn)
    conn.execute(
        """
        INSERT INTO dim_legislator (
            bioguide_id, full_name, chamber, state, district_2025,
            party, term_start, term_end, first_elected, is_incumbent
        ) VALUES ('A0000001', 'Ann Alpha', 'House', 'VA', 1, 'D',
                  DATE '2025-01-03', DATE '2027-01-03', 2018, TRUE)
        """
    )
    conn.execute(
        """
        INSERT INTO dim_bill (bill_id, congress, bill_type, title) VALUES
          ('hr-10-119', 119, 'hr', 'Real Policy Act'),
          ('hres-99-119', 119, 'hres',
           'Providing for consideration of the bill (H.R. 10) the Real Policy Act')
        """
    )
    conn.execute(
        """
        INSERT INTO fact_vote (
            vote_id, congress, session, chamber, roll_number, vote_date,
            vote_question, vote_category, bill_id
        ) VALUES
          ('h-119-1-10', 119, 1, 'House', 10, DATE '2025-03-01',
           'On Passage', 'PASSAGE', 'hr-10-119'),
          ('h-119-1-99', 119, 1, 'House', 99, DATE '2025-03-02',
           'On Agreeing to the Resolution', 'PASSAGE', 'hres-99-119')
        """
    )
    for vid in ("h-119-1-10", "h-119-1-99"):
        conn.execute(
            "INSERT INTO fact_member_vote (vote_id, bioguide_id, position) VALUES (?, 'A0000001', 'YEA')",
            [vid],
        )
        set_valence(conn, vote_id=vid, impact_tag="FEDERAL_CONTRACTING", valence=1, source="HUMAN")

    cfg = load_scoring_config()
    try:
        pair_ids = {p["vote_id"] for p in scoreable_pairs(conn, cfg)}
        frame = build_scores_frame(conn, cfg, map_version="2021")
    finally:
        conn.close()

    assert "h-119-1-10" in pair_ids  # substantive passage kept
    assert "h-119-1-99" not in pair_ids  # special rule dropped
    cell = _by_bio(frame)["A0000001"]
    assert cell["n_contested"] == 1  # only the real passage counts


def test_frame_is_empty_without_valence(tmp_path: Path) -> None:
    """No adjudicated valence → nothing is scoreable → empty frame (fail-closed)."""
    path = tmp_path / "w.duckdb"
    conn = connect(path)
    ensure_schema(conn)
    conn.execute(
        """
        INSERT INTO dim_legislator (
            bioguide_id, full_name, chamber, state, district_2025,
            party, term_start, term_end, first_elected, is_incumbent
        ) VALUES ('A0000001', 'Ann Alpha', 'House', 'VA', 1, 'D',
                  DATE '2025-01-03', DATE '2027-01-03', 2018, TRUE)
        """
    )
    conn.execute(
        """
        INSERT INTO fact_vote (
            vote_id, congress, session, chamber, roll_number, vote_date,
            vote_category
        ) VALUES ('h-119-1-1', 119, 1, 'House', 1, DATE '2025-03-01', 'PASSAGE')
        """
    )
    conn.execute(
        "INSERT INTO fact_member_vote (vote_id, bioguide_id, position) "
        "VALUES ('h-119-1-1', 'A0000001', 'YEA')"
    )
    try:
        frame = build_scores_frame(conn, map_version="2021")
    finally:
        conn.close()
    assert frame == []


# --------------------------------------------------------------------------- #
# Valence storage + proposals
# --------------------------------------------------------------------------- #
def test_set_valence_upserts(warehouse: Path) -> None:
    conn = connect(warehouse)
    try:
        set_valence(
            conn, vote_id="h-119-1-1", impact_tag="FEDERAL_CONTRACTING", valence=-1, source="HUMAN"
        )
        v = load_valence(conn)[("h-119-1-1", "FEDERAL_CONTRACTING")]
    finally:
        conn.close()
    assert v == (-1, "HUMAN")


def test_set_valence_rejects_bad_value(warehouse: Path) -> None:
    conn = connect(warehouse)
    try:
        with pytest.raises(ValueError):
            set_valence(
                conn, vote_id="h-119-1-1", impact_tag="X", valence=2, source="HUMAN"
            )
    finally:
        conn.close()


def test_cli_valence_set_accepts_negative_value(tmp_path: Path) -> None:
    """`valence set ... -1` must not be parsed as an option (regression)."""
    from typer.testing import CliRunner

    from vact.cli import app

    path = tmp_path / "w.duckdb"
    conn = connect(path)
    ensure_schema(conn)
    conn.close()
    result = CliRunner().invoke(
        app, ["valence", "set", "h-1", "FEDERAL_CONTRACTING", "-1", "--warehouse", str(path)]
    )
    assert result.exit_code == 0, result.output
    conn = connect(path)
    try:
        assert load_valence(conn)[("h-1", "FEDERAL_CONTRACTING")] == (-1, "HUMAN")
    finally:
        conn.close()


def test_propose_valence_writes_rule_rows_only_on_match(warehouse: Path) -> None:
    # Custom config: a FEDERAL_CONTRACTING rule that matches "Buy American".
    cfg = ScoringConfig(
        version=1,
        axis_name="t",
        axis_description="",
        include_categories=frozenset({"PASSAGE"}),
        exclude_categories=frozenset({"CLOTURE"}),
        min_contested=3,
        wilson_z=1.96,
        min_eligible_for_display=3,
        valence_rules={"FEDERAL_CONTRACTING": [(re.compile("buy american", re.I), 1)]},
    )
    conn = connect(warehouse)
    try:
        # A tagged PASSAGE vote whose bill mentions "Buy American".
        conn.execute(
            """
            INSERT INTO dim_bill (bill_id, congress, bill_type, bill_number, title)
            VALUES ('hr-7-119', 119, 'hr', 7, 'Buy American Procurement Act')
            """
        )
        conn.execute("UPDATE fact_vote SET bill_id = 'hr-7-119' WHERE vote_id = 'h-119-1-8'")
        conn.execute(
            "INSERT INTO bridge_vote_impact (vote_id, impact_tag, confidence, classified_by) "
            "VALUES ('h-119-1-8', 'FEDERAL_CONTRACTING', 1.0, 'RULE')"
        )
        # h-119-1-8 has no valence yet (fixture skipped it) → eligible to propose.
        stats = propose_valence(conn, cfg, new_only=True)
        v = load_valence(conn).get(("h-119-1-8", "FEDERAL_CONTRACTING"))
    finally:
        conn.close()
    assert stats["proposed"] == 1
    assert v == (1, "RULE")
