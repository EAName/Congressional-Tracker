"""Tests for warehouse schema, category rules, and MERGE loads."""

from __future__ import annotations

from pathlib import Path

import pytest

from vact.models.votes import VotePosition
from vact.sources import house_rollcalls as house
from vact.sources import legislators as legislator_source
from vact.sources import senate_rollcalls as senate
from vact.transforms.ids import canonical_vote_id, parse_bill_ref
from vact.transforms.lis_crosswalk import build_lis_bioguide_crosswalk
from vact.transforms.vote_category import classify_vote_category
from vact.warehouse.connection import connect, ensure_schema
from vact.warehouse.load import load_house_vote, load_senate_vote


@pytest.fixture()
def warehouse(tmp_path: Path):
    path = tmp_path / "warehouse.duckdb"
    conn = connect(path)
    ensure_schema(conn)
    yield conn
    conn.close()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("H R 2966", "hr-2966-119"),
        ("H.R. 2966", "hr-2966-119"),
        ("S. 1582", "s-1582-119"),
        ("H RES 499", "hres-499-119"),
        ("PN11-18", "pn-11-18-119"),
        ("PN 11-18", "pn-11-18-119"),
    ],
)
def test_parse_bill_ref(raw: str, expected: str) -> None:
    ref = parse_bill_ref(raw, 119)
    assert ref is not None
    assert ref.bill_id == expected


def test_canonical_vote_id() -> None:
    assert canonical_vote_id("House", 119, 1, 156) == "h-119-1-156"
    assert canonical_vote_id("Senate", 119, 2, 380) == "s-119-2-380"


@pytest.mark.parametrize(
    ("question", "vote_type", "expected"),
    [
        ("On Passage", "YEA-AND-NAY", "PASSAGE"),
        ("On Motion to Suspend the Rules and Pass", None, "SUSPENSION"),
        ("Passage under Suspension", None, "SUSPENSION"),
        ("On Motion to Recommit", None, "MOTION_TO_RECOMMIT"),
        ("On Agreeing to the Amendment", "RECORDED VOTE", "AMENDMENT"),
        ("On the Nomination", None, "NOMINATION"),
        ("Motion to Invoke Cloture", None, "CLOTURE"),
        ("On Ordering the Previous Question", None, "PROCEDURAL"),
        ("Something obscure", None, "PROCEDURAL"),
    ],
)
def test_vote_category_from_sql_rules(
    warehouse, question: str, vote_type: str | None, expected: str
) -> None:
    # Fix suspension phrasing used by House: often "On Motion to Suspend the Rules and Pass"
    assert classify_vote_category(question, vote_type, conn=warehouse) == expected


def test_suspension_distinct_from_passage(warehouse) -> None:
    assert classify_vote_category("On Passage", None, conn=warehouse) == "PASSAGE"
    assert (
        classify_vote_category(
            "On Motion to Suspend the Rules and Pass", None, conn=warehouse
        )
        == "SUSPENSION"
    )


def test_load_house_and_senate_idempotent(warehouse) -> None:
    # Use real cached raw files when present; otherwise skip network.
    house_path = house.raw_roll_path(2025, 156)
    if not house_path.exists():
        pytest.skip("house roll 156 not cached")
    senate_path = senate.raw_roll_path(119, 1, 318)
    if not senate_path.exists():
        pytest.skip("senate roll 318 not cached")

    hv, hm = house.parse(house_path)
    vid_h = load_house_vote(hv, hm, conn=warehouse)
    assert vid_h == "h-119-1-156"
    before_h = warehouse.execute(
        "SELECT COUNT(*) FROM fact_member_vote WHERE vote_id = ?", [vid_h]
    ).fetchone()[0]
    load_house_vote(hv, hm, conn=warehouse)
    after_h = warehouse.execute(
        "SELECT COUNT(*) FROM fact_member_vote WHERE vote_id = ?", [vid_h]
    ).fetchone()[0]
    assert before_h == after_h == len(hm)

    paths = legislator_source.fetch_all()
    xw = build_lis_bioguide_crosswalk(
        legislator_source.parse_legislators(paths["legislators-current"])
        + legislator_source.parse_legislators(paths["legislators-historical"])
    )
    sv, sm = senate.parse(senate_path, lis_to_bioguide=xw)
    vid_s = load_senate_vote(sv, sm, conn=warehouse)
    assert vid_s == "s-119-1-318"
    load_senate_vote(sv, sm, conn=warehouse)
    n_votes = warehouse.execute("SELECT COUNT(*) FROM fact_vote").fetchone()[0]
    assert n_votes == 2

    cat = warehouse.execute(
        "SELECT vote_category, bill_id FROM fact_vote WHERE vote_id = ?", [vid_h]
    ).fetchone()
    assert cat[0] == "PASSAGE"
    assert cat[1] == "hr-2966-119"

    # Member position preserved as canonical enum
    sample = warehouse.execute(
        """
        SELECT position FROM fact_member_vote
        WHERE vote_id = ? AND bioguide_id = 'W000804'
        """,
        [vid_h],
    ).fetchone()
    assert sample[0] == VotePosition.YEA.value
