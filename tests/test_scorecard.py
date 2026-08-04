"""Scorecard suppression and bill-level aggregation (FIX 1 + FIX 2)."""

from __future__ import annotations

from pathlib import Path

from vact.exports import data as data_mod
from vact.transforms.districts import build_dim_district_rows
from vact.warehouse.connection import connect, ensure_schema
from vact.warehouse.load import upsert_dim_district


def _seed_scorecard_warehouse(path: Path) -> None:
    conn = connect(path)
    ensure_schema(conn)
    upsert_dim_district(build_dim_district_rows(), conn=conn)
    conn.execute(
        """
        INSERT INTO dim_legislator (
            bioguide_id, full_name, chamber, state, district_current,
            district_2025, district_2026, party, term_start, term_end,
            first_elected, is_incumbent
        ) VALUES
          ('W000804', 'Robert J. Wittman', 'House', 'VA', 1, 1, 1, 'Republican',
           DATE '2025-01-03', DATE '2027-01-03', 2007, TRUE)
        """
    )
    conn.execute(
        """
        INSERT INTO dim_bill VALUES
          ('hr-3617-119', 119, 'hr', 3617, '3617', 'Input Costs Bill', NULL,
           NULL, NULL, NULL, NULL),
          ('hr-3838-119', 119, 'hr', 3838, '3838', 'Contracting Omnibus', NULL,
           NULL, NULL, NULL, NULL),
          ('hres-1057-119', 119, 'hres', 1057, '1057', 'House Rules', NULL,
           NULL, NULL, NULL, NULL)
        """
    )
    conn.execute(
        """
        INSERT INTO fact_vote (
            vote_id, congress, session, chamber, roll_number, vote_date,
            vote_question, vote_type, vote_category, result, passed, bill_id,
            yea_total, nay_total, present_total, not_voting_total, source_url
        ) VALUES
          ('h-119-2-63', 119, 2, 'House', 63, DATE '2026-02-11',
           'On Motion to Recommit', NULL, 'MOTION_TO_RECOMMIT', 'Failed', FALSE,
           'hr-3617-119', 0, 1, 0, 0, 'https://clerk.house.gov/evs/2026/roll063.xml'),
          ('h-119-2-64', 119, 2, 'House', 64, DATE '2026-02-11',
           'On Passage', NULL, 'PASSAGE', 'Passed', TRUE,
           'hr-3617-119', 1, 0, 0, 0, 'https://clerk.house.gov/evs/2026/roll064.xml'),
          ('h-119-1-901', 119, 1, 'House', 901, DATE '2025-09-10',
           'Amendment A', NULL, 'AMENDMENT', 'Agreed to', TRUE,
           'hr-3838-119', 1, 0, 0, 0, 'https://clerk.house.gov/evs/2025/roll901.xml'),
          ('h-119-1-902', 119, 1, 'House', 902, DATE '2025-09-10',
           'Amendment B', NULL, 'AMENDMENT', 'Agreed to', TRUE,
           'hr-3838-119', 1, 0, 0, 0, 'https://clerk.house.gov/evs/2025/roll902.xml'),
          ('h-119-1-903', 119, 1, 'House', 903, DATE '2025-09-10',
           'On Passage', NULL, 'PASSAGE', 'Passed', TRUE,
           'hr-3838-119', 0, 1, 0, 0, 'https://clerk.house.gov/evs/2025/roll903.xml'),
          ('h-119-1-50', 119, 1, 'House', 50, DATE '2025-06-01',
           'On Ordering the Previous Question', NULL, 'PROCEDURAL', 'Passed', TRUE,
           'hres-1057-119', 1, 0, 0, 0, 'https://clerk.house.gov/evs/2025/roll050.xml'),
          ('h-119-1-51', 119, 1, 'House', 51, DATE '2025-06-01',
           'On Agreeing to the Resolution', NULL, 'PASSAGE', 'Passed', TRUE,
           'hres-1057-119', 1, 0, 0, 0, 'https://clerk.house.gov/evs/2025/roll051.xml')
        """
    )
    conn.execute(
        """
        INSERT INTO fact_member_vote VALUES
          ('h-119-2-63', 'W000804', 'NAY'),
          ('h-119-2-64', 'W000804', 'YEA'),
          ('h-119-1-901', 'W000804', 'YEA'),
          ('h-119-1-902', 'W000804', 'YEA'),
          ('h-119-1-903', 'W000804', 'NAY'),
          ('h-119-1-50', 'W000804', 'YEA'),
          ('h-119-1-51', 'W000804', 'YEA')
        """
    )
    conn.execute(
        """
        INSERT INTO bridge_vote_impact VALUES
          ('h-119-2-63', 'INPUT_COSTS', 1.0, 'RULE'),
          ('h-119-2-64', 'INPUT_COSTS', 1.0, 'RULE'),
          ('h-119-1-901', 'FEDERAL_CONTRACTING', 1.0, 'RULE'),
          ('h-119-1-902', 'FEDERAL_CONTRACTING', 1.0, 'RULE'),
          ('h-119-1-903', 'FEDERAL_CONTRACTING', 1.0, 'RULE'),
          ('h-119-1-50', 'HEALTH_COSTS', 1.0, 'RULE'),
          ('h-119-1-51', 'HEALTH_COSTS', 1.0, 'RULE')
        """
    )
    conn.close()


def test_scorecard_excludes_suppressed_categories(tmp_path: Path) -> None:
    wh = tmp_path / "w.duckdb"
    _seed_scorecard_warehouse(wh)
    conn = connect(wh)
    try:
        data_mod.assert_scorecard_excludes_suppressed(conn)
    finally:
        conn.close()


def test_scorecard_bill_level_not_raw_roll_calls(tmp_path: Path) -> None:
    wh = tmp_path / "w.duckdb"
    _seed_scorecard_warehouse(wh)
    conn = connect(wh)
    try:
        member = {
            "bioguide_id": "W000804",
            "full_name": "Robert J. Wittman",
            "chamber": "House",
            "party": "Republican",
            "district_number": 1,
            "partisan_lean": "D lean",
            "is_target": True,
        }
        row = data_mod.member_scorecard_row(conn, member)

        # MTR NAY + PASSAGE YEA on same bill → one bill, passage wins → 1Y / 0N.
        assert row["INPUT_COSTS"] == "1Y / 0N of 1 bills"
        assert row["INPUT_COSTS_yea"] == 1
        assert row["INPUT_COSTS_nay"] == 0
        assert row["INPUT_COSTS_bills"] == 1

        # Two amendments + passage NAY on same bill → one bill, passage wins → NAY.
        assert row["FEDERAL_CONTRACTING"] == "0Y / 1N of 1 bills"
        assert row["FEDERAL_CONTRACTING_bills"] == 1

        # hres previous-question + adoption never enter scorecard.
        assert row["HEALTH_COSTS"] == data_mod.EMPTY_SCORE_LABEL
        assert row["HEALTH_COSTS_bills"] == 0

        assert "—" not in row["TAX_BURDEN"]
        assert row["TAX_BURDEN"] == data_mod.EMPTY_SCORE_LABEL
        assert row["bills_counted"] == 2
    finally:
        conn.close()
