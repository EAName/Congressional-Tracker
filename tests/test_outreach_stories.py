"""Outreach story queue and publish funnel helpers."""

from __future__ import annotations

from pathlib import Path

from vact.exports import data as data_mod
from vact.transforms.districts import build_dim_district_rows
from vact.warehouse.connection import connect, ensure_schema
from vact.warehouse.load import upsert_dim_district


def _seed(path: Path) -> None:
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
           DATE '2025-01-03', DATE '2027-01-03', 2007, TRUE),
          ('K000399', 'Jennifer A. Kiggans', 'House', 'VA', 2, 2, 2, 'Republican',
           DATE '2025-01-03', DATE '2027-01-03', 2023, TRUE),
          ('M001239', 'John J. McGuire III', 'House', 'VA', 5, 5, 5, 'Republican',
           DATE '2025-01-03', DATE '2027-01-03', 2025, TRUE),
          ('C001118', 'Ben Cline', 'House', 'VA', 6, 6, 6, 'Republican',
           DATE '2025-01-03', DATE '2027-01-03', 2019, TRUE),
          ('S000185', 'Robert C. Scott', 'House', 'VA', 3, 3, 3, 'Democrat',
           DATE '2025-01-03', DATE '2027-01-03', 1993, TRUE),
          ('M001222', 'Jennifer McClellan', 'House', 'VA', 4, 4, 4, 'Democrat',
           DATE '2025-01-03', DATE '2027-01-03', 2023, TRUE)
        """
    )
    conn.execute(
        """
        INSERT INTO dim_bill VALUES
          ('hr-10-119', 119, 'hr', 10, '10', 'SBA Lending Act', NULL,
           'Expands SBA 7(a) loans for small firms.', NULL, NULL, NULL)
        """
    )
    conn.execute(
        """
        INSERT INTO fact_vote (
            vote_id, congress, session, chamber, roll_number, vote_date,
            vote_question, vote_type, vote_category, result, passed, bill_id,
            yea_total, nay_total, present_total, not_voting_total, source_url
        ) VALUES
          ('h-119-1-50', 119, 1, 'House', 50, DATE '2025-06-01',
           'On Passage', NULL, 'PASSAGE', 'Passed', TRUE, 'hr-10-119',
           2, 4, 0, 0, 'https://clerk.house.gov/evs/2025/roll050.xml')
        """
    )
    # Dem YEA, Target Four NAY → party-line split.
    conn.execute(
        """
        INSERT INTO fact_member_vote VALUES
          ('h-119-1-50', 'S000185', 'YEA'),
          ('h-119-1-50', 'M001222', 'YEA'),
          ('h-119-1-50', 'W000804', 'NAY'),
          ('h-119-1-50', 'K000399', 'NAY'),
          ('h-119-1-50', 'M001239', 'NAY'),
          ('h-119-1-50', 'C001118', 'NAY')
        """
    )
    conn.execute(
        """
        INSERT INTO bridge_vote_impact VALUES
          ('h-119-1-50', 'ACCESS_TO_CAPITAL', 1.0, 'RULE')
        """
    )
    conn.close()


def test_publication_funnel_and_story_queue(tmp_path: Path) -> None:
    wh = tmp_path / "w.duckdb"
    _seed(wh)
    conn = connect(wh)
    try:
        funnel = data_mod.publication_funnel(conn)
        assert [s["stage"] for s in funnel] == [
            "Tagged substantive votes",
            "Party-line VA splits",
            "Narrative briefs ready",
        ]
        assert funnel[0]["count"] == 1
        assert funnel[1]["count"] == 1
        assert funnel[2]["count"] == 1

        stories = data_mod.build_outreach_stories(conn, limit=5)
        assert len(stories) == 1
        story = stories[0]
        assert story["vote_id"] == "h-119-1-50"
        assert story["dem_position"] == "YEA"
        assert story["gop_position"] == "NAY"
        assert story["target_disagree_n"] == 4
        assert story["summary_ready"] is True
        assert story["score"] >= 10 + 5 + 12 + 10
        assert len(story["target_positions"]) == 4
    finally:
        conn.close()
