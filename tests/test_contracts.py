"""Warehouse contract tests (Prompt 8)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from vact.exports.publication import assert_publication_gates, list_publication_votes
from vact.models.votes import VotePosition
from vact.warehouse.connection import connect, ensure_schema
from vact.warehouse.contracts import (
    MemberTotalsMismatchError,
    assert_all_warehouse_contracts,
    assert_freshness_contract,
    assert_member_totals_match,
    assert_referential_contracts,
    assert_source_contracts,
    assert_vote_id_canonical,
    is_congress_in_session,
    session_date_bounds,
)
from vact.warehouse.load import load_house_vote
from vact.sources import house_rollcalls as house


@pytest.fixture()
def empty_warehouse(tmp_path: Path):
    path = tmp_path / "w.duckdb"
    conn = connect(path)
    ensure_schema(conn)
    yield conn
    conn.close()


def test_vote_id_regex() -> None:
    assert_vote_id_canonical("h-119-1-156")
    assert_vote_id_canonical("s-119-2-380")
    with pytest.raises(ValueError):
        assert_vote_id_canonical("H-119-1-156")
    with pytest.raises(ValueError):
        assert_vote_id_canonical("h-119-3-1")


def test_session_bounds_119() -> None:
    assert session_date_bounds(119, 1) == (date(2025, 1, 3), date(2026, 1, 3))
    assert session_date_bounds(119, 2) == (date(2026, 1, 3), date(2027, 1, 3))


def test_member_totals_mismatch_raises() -> None:
    with pytest.raises(MemberTotalsMismatchError):
        assert_member_totals_match(
            vote_id="h-119-1-1",
            positions=[VotePosition.YEA, VotePosition.NAY],
            yea=2,
            nay=0,
            present=0,
            not_voting=0,
        )


def test_ingest_fails_on_tampered_totals(empty_warehouse) -> None:
    house_path = house.raw_roll_path(2025, 156)
    if not house_path.exists():
        pytest.skip("house roll 156 not cached")
    vote, members = house.parse(house_path)
    # Mutate XML-derived totals so member counts no longer match.
    vote.totals.yea = vote.totals.yea + 1
    with pytest.raises(MemberTotalsMismatchError):
        load_house_vote(vote, members, conn=empty_warehouse)


def test_publication_gates_reject_missing_summary_and_llm(empty_warehouse) -> None:
    conn = empty_warehouse
    conn.execute(
        """
        INSERT INTO dim_bill VALUES
          ('hr-1-119', 119, 'hr', 1, '1', 'Tax Act', NULL, NULL, NULL, NULL, NULL),
          ('hr-2-119', 119, 'hr', 2, '2', 'Ready Act', NULL, 'Cuts small-business paperwork.', NULL, NULL, NULL)
        """
    )
    conn.execute(
        """
        INSERT INTO fact_vote (
            vote_id, congress, session, chamber, roll_number, vote_date,
            vote_question, vote_type, vote_category, result, passed, bill_id,
            yea_total, nay_total, present_total, not_voting_total, source_url
        ) VALUES
          ('h-119-1-1', 119, 1, 'House', 1, DATE '2025-03-01', 'On Passage', NULL, 'PASSAGE',
           'Passed', TRUE, 'hr-1-119', 1, 0, 0, 0, 'http://x'),
          ('h-119-1-2', 119, 1, 'House', 2, DATE '2025-03-02', 'On Passage', NULL, 'PASSAGE',
           'Passed', TRUE, 'hr-2-119', 1, 0, 0, 0, 'http://x'),
          ('h-119-1-3', 119, 1, 'House', 3, DATE '2025-03-03', 'On Passage', NULL, 'PASSAGE',
           'Passed', TRUE, 'hr-2-119', 1, 0, 0, 0, 'http://x')
        """
    )
    conn.execute(
        """
        INSERT INTO bridge_vote_impact VALUES
          ('h-119-1-1', 'TAX_BURDEN', 1.0, 'RULE'),
          ('h-119-1-2', 'TAX_BURDEN', 1.0, 'RULE'),
          ('h-119-1-3', 'TAX_BURDEN', 0.7, 'LLM')
        """
    )

    published = {r["vote_id"] for r in list_publication_votes(conn)}
    assert "h-119-1-1" not in published  # no summary
    assert "h-119-1-2" in published
    assert "h-119-1-3" not in published  # naked LLM
    assert_publication_gates(conn)


def test_freshness_skipped_in_august_recess() -> None:
    # August 3, 2026 is a Monday in August → recess heuristic.
    assert not is_congress_in_session(date(2026, 8, 3))


def test_live_warehouse_contracts() -> None:
    """Run full contracts against the project warehouse when populated."""
    from vact.paths import WAREHOUSE_PATH

    if not WAREHOUSE_PATH.exists():
        pytest.skip("project warehouse not built")
    conn = connect(WAREHOUSE_PATH)
    try:
        ensure_schema(conn)
        n = conn.execute("SELECT COUNT(*) FROM fact_vote").fetchone()[0]
        if n == 0:
            pytest.skip("warehouse empty")
        assert_source_contracts(conn)
        assert_referential_contracts(conn)
        assert_publication_gates(conn)
        assert_freshness_contract(conn, as_of=date.today())
        assert_all_warehouse_contracts(conn)
    finally:
        conn.close()
