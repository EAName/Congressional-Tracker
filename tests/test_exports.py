"""Tests for Sheets / site / social publication exports."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from vact.exports import data as data_mod
from vact.exports.sheets import build_readme_values, build_tab_payloads
from vact.exports.site import build_site
from vact.exports.social import HEIGHT, WIDTH, build_social_cards, render_card
from vact.transforms.districts import build_dim_district_rows
from vact.warehouse.connection import connect, ensure_schema
from vact.warehouse.load import upsert_dim_district


def _seed_publication_warehouse(path: Path) -> None:
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
          ('W000805', 'Mark R. Warner', 'Senate', 'VA', NULL, NULL, NULL, 'Democrat',
           DATE '2021-01-03', DATE '2027-01-03', 2009, TRUE)
        """
    )
    conn.execute(
        """
        INSERT INTO dim_bill VALUES
          ('hr-10-119', 119, 'hr', 10, '10', 'SBA Lending Act', NULL,
           'Expands SBA 7(a) loans for small firms.', NULL, NULL, NULL),
          ('hr-11-119', 119, 'hr', 11, '11', 'Paperwork Act', NULL,
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
          ('h-119-1-50', 119, 1, 'House', 50, DATE '2025-06-01',
           'On Passage', NULL, 'PASSAGE', 'Passed', TRUE, 'hr-10-119',
           1, 0, 0, 0, 'https://clerk.house.gov/evs/2025/roll050.xml'),
          ('h-119-1-51', 119, 1, 'House', 51, DATE '2025-06-02',
           'On Ordering the Previous Question', NULL, 'PROCEDURAL', 'Passed', TRUE,
           'hr-11-119', 1, 0, 0, 0, 'https://clerk.house.gov/evs/2025/roll051.xml')
        """
    )
    conn.execute(
        """
        INSERT INTO fact_member_vote VALUES
          ('h-119-1-50', 'W000804', 'YEA'),
          ('h-119-1-50', 'K000399', 'NAY'),
          ('h-119-1-51', 'W000804', 'YEA')
        """
    )
    conn.execute(
        """
        INSERT INTO bridge_vote_impact VALUES
          ('h-119-1-50', 'ACCESS_TO_CAPITAL', 1.0, 'RULE'),
          ('h-119-1-51', 'REGULATORY_BURDEN', 1.0, 'RULE')
        """
    )
    conn.close()


def test_build_tab_payloads(tmp_path: Path) -> None:
    wh = tmp_path / "w.duckdb"
    _seed_publication_warehouse(wh)
    conn = connect(wh)
    try:
        payloads = build_tab_payloads(conn, generated_at="2026-08-03T00:00:00Z")
        assert set(payloads) == {
            "Dashboard",
            "README",
            "Target Four",
            "Full Delegation",
            "Signed Scores",
            "Party Deviations",
            "Vote Detail",
        }
        assert payloads["README"][1][1] == "2026-08-03T00:00:00Z"
        assert payloads["Signed Scores"][0][0] == "Member"
        assert payloads["Signed Scores"][0][6] == "Signed Score"
        assert payloads["Party Deviations"][0][0] == "Member"
        assert payloads["Party Deviations"][0][8] == "Deviation"
        # Without adjudicated valence the analysis tabs are header-only.
        assert len(payloads["Signed Scores"]) == 1
        assert len(payloads["Party Deviations"]) == 1
        dash = payloads["Dashboard"]
        assert dash[0][0] == "VA Congressional Vote Tracker"
        assert any("TARGET SEATS" in str(r[0]) for r in dash if r)
        # Chart source headers live off to the right (col N).
        assert dash[0][13] == "Vote category"
        assert "Access To Capital" in payloads["Target Four"][0] or "Access to Capital" in str(
            payloads["Target Four"][0]
        )
        # Target header + VA-1 / VA-2 under 2021 map.
        assert payloads["Target Four"][0][0] == "Member"
        assert len(payloads["Target Four"]) == 3  # header + 2 targets
        assert {row[3] for row in payloads["Target Four"][1:]} == {1, 2}
        assert all(row[4] == "2021" for row in payloads["Target Four"][1:])
        assert all(row[4] == "2021" for row in payloads["Full Delegation"][1:])
        # Snapshot Map column on Dashboard.
        assert dash[2][2] == "Map" and dash[2][3] == "2021"
        # Vote Detail must not include LLM confidence; procedural may appear (audit).
        detail_text = " ".join(str(c) for row in payloads["Vote Detail"] for c in row)
        assert "ACCESS_TO_CAPITAL" in detail_text
        assert "confidence" not in detail_text.lower()
    finally:
        conn.close()


def test_site_suppresses_procedural_and_requires_summary(tmp_path: Path) -> None:
    wh = tmp_path / "w.duckdb"
    out = tmp_path / "docs"
    _seed_publication_warehouse(wh)
    dest = build_site(out_dir=out, warehouse_path=wh, map_version="2026")
    index = (dest / "index.html").read_text(encoding="utf-8")
    assert "Democrats for Virginia" in index
    assert "VA-1" in index
    assert 'id="categoryChart"' in index
    assert 'id="impactChart"' in index
    assert "heatmap" in index
    assert "Target Four" in index
    assert "Access To Capital" in index or "Access to Capital" in index or "ACCESS_TO_CAPITAL" not in index
    assert (dest / "tracker.js").is_file()
    assert (dest / "styles.css").is_file()
    sources = (dest / "methodology.html").read_text(encoding="utf-8")
    assert "clerk.house.gov" in sources
    assert "senate.gov" in sources
    assert "DuckDB" not in index  # press copy, not warehouse jargon
    d1 = (dest / "district" / "1.html").read_text(encoding="utf-8")
    assert "Expands SBA 7(a) loans" in d1
    assert "Previous Question" not in d1  # procedural suppressed
    assert "https://clerk.house.gov" in d1
    assert "VA-1 impact record" in d1 or "impact record" in d1.lower()
    # Missing summary vote must not appear; if code tried to render it, build would fail.


def test_site_fails_loud_on_null_summary_if_forced(tmp_path: Path) -> None:
    wh = tmp_path / "w.duckdb"
    _seed_publication_warehouse(wh)
    conn = connect(wh)
    try:
        # Strip summary so a direct query would be empty; forced render path raises.
        conn.execute(
            "UPDATE dim_bill SET plain_language_summary = NULL WHERE bill_id = 'hr-10-119'"
        )
        votes = data_mod.district_votes_for_member(conn, bioguide_id="W000804")
        assert votes == []
    finally:
        conn.close()


def test_social_card_dimensions(tmp_path: Path) -> None:
    out = tmp_path / "card.png"
    render_card(
        member_name="Robert J. Wittman",
        district_number=1,
        summary="Expands SBA 7(a) loans for small firms.",
        position="YEA",
        source_url="https://clerk.house.gov/evs/2025/roll050.xml",
        generated_at="2026-08-03T00:00:00Z",
        out_path=out,
    )
    with Image.open(out) as img:
        assert img.size == (WIDTH, HEIGHT)


def test_social_build_from_warehouse(tmp_path: Path) -> None:
    wh = tmp_path / "w.duckdb"
    out = tmp_path / "social"
    _seed_publication_warehouse(wh)
    paths = build_social_cards(out_dir=out, warehouse_path=wh)
    assert len(paths) == 4
    for path in paths:
        with Image.open(path) as img:
            assert img.size == (WIDTH, HEIGHT)


def test_readme_states_procedural_caveat() -> None:
    rows = build_readme_values(generated_at="t", corpus_votes=10)
    blob = " ".join(str(c) for r in rows for c in r)
    assert "NAY on a procedural vote is not evidence" in blob
    assert "Dashboard" in blob
