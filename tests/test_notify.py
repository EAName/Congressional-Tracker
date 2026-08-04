"""Tests for Prompt 10 scheduling helpers (dimensions meta + outreach notify)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from vact.pipeline.notify import find_party_line_splits
from vact.transforms.districts import build_dim_district_rows
from vact.warehouse.connection import connect, ensure_schema
from vact.warehouse.load import upsert_dim_district
from vact.warehouse.meta import (
    META_LEGISLATORS_SHA,
    get_meta,
    set_meta,
    warehouse_content_fingerprint,
)


def test_meta_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "w.duckdb"
    conn = connect(path)
    try:
        ensure_schema(conn)
        assert get_meta(conn, META_LEGISLATORS_SHA) is None
        set_meta(conn, META_LEGISLATORS_SHA, "abc123")
        assert get_meta(conn, META_LEGISLATORS_SHA) == "abc123"
        set_meta(conn, META_LEGISLATORS_SHA, "def456")
        assert get_meta(conn, META_LEGISLATORS_SHA) == "def456"
        fp = warehouse_content_fingerprint(conn)
        assert isinstance(fp, str)
    finally:
        conn.close()


def test_party_line_split_detection(tmp_path: Path) -> None:
    path = tmp_path / "w.duckdb"
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
          ('D000001', 'Dem Member', 'House', 'VA', 7, 7, 7, 'Democrat',
           DATE '2025-01-03', DATE '2027-01-03', 2025, TRUE),
          ('R000001', 'GOP Member', 'House', 'VA', 1, 1, 1, 'Republican',
           DATE '2025-01-03', DATE '2027-01-03', 2025, TRUE)
        """
    )
    conn.execute(
        """
        INSERT INTO dim_bill VALUES
          ('hr-9-119', 119, 'hr', 9, '9', 'Tax Act', NULL, 'Cuts pass-through taxes.', NULL, NULL, NULL)
        """
    )
    conn.execute(
        """
        INSERT INTO fact_vote (
            vote_id, congress, session, chamber, roll_number, vote_date,
            vote_question, vote_type, vote_category, result, passed, bill_id,
            yea_total, nay_total, present_total, not_voting_total, source_url
        ) VALUES
          ('h-119-1-90', 119, 1, 'House', 90, DATE '2025-06-01',
           'On Passage', NULL, 'PASSAGE', 'Passed', TRUE, 'hr-9-119',
           1, 1, 0, 0, 'https://clerk.house.gov/x'),
          ('h-119-1-91', 119, 1, 'House', 91, DATE '2025-06-02',
           'On Ordering the Previous Question', NULL, 'PROCEDURAL', 'Passed', TRUE,
           'hr-9-119', 1, 1, 0, 0, 'https://clerk.house.gov/y')
        """
    )
    conn.execute(
        """
        INSERT INTO fact_member_vote VALUES
          ('h-119-1-90', 'D000001', 'YEA'),
          ('h-119-1-90', 'R000001', 'NAY'),
          ('h-119-1-91', 'D000001', 'YEA'),
          ('h-119-1-91', 'R000001', 'NAY')
        """
    )
    conn.execute(
        """
        INSERT INTO bridge_vote_impact VALUES
          ('h-119-1-90', 'TAX_BURDEN', 1.0, 'RULE'),
          ('h-119-1-91', 'TAX_BURDEN', 1.0, 'RULE')
        """
    )

    signals = find_party_line_splits(conn)
    ids = {s.vote_id for s in signals}
    assert "h-119-1-90" in ids
    assert "h-119-1-91" not in ids  # procedural suppressed
    assert signals[0].dem_position == "YEA"
    assert signals[0].gop_position == "NAY"
    conn.close()


def test_dimensions_skip_when_sha_matches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from vact.pipeline import dimensions as dim

    path = tmp_path / "w.duckdb"
    conn = connect(path)
    ensure_schema(conn)
    set_meta(conn, META_LEGISLATORS_SHA, "deadbeef")
    conn.close()

    monkeypatch.setattr(dim, "fetch_upstream_legislators_sha", lambda: "deadbeef")
    result = dim.refresh_dimensions(warehouse_path=path)
    assert result.skipped is True
    assert result.changed is False
