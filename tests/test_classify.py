"""Tests for impact taxonomy classifier."""

from __future__ import annotations

from pathlib import Path

import pytest

from vact.transforms.classify import (
    IMPACT_TAGS,
    classify_corpus,
    classify_rules,
    load_rulebook,
    promote_review_queue,
    reclassify_all,
)
from vact.warehouse.connection import connect, ensure_schema


@pytest.fixture()
def warehouse(tmp_path: Path) -> Path:
    path = tmp_path / "warehouse.duckdb"
    conn = connect(path)
    ensure_schema(conn)
    conn.execute(
        """
        INSERT INTO fact_vote (
            vote_id, congress, session, chamber, roll_number, vote_date,
            vote_question, vote_type, vote_category, result, passed, bill_id,
            yea_total, nay_total, present_total, not_voting_total, source_url
        ) VALUES
          ('h-119-1-100', 119, 1, 'House', 100, DATE '2025-03-01',
           'On Passage of the Small Business Administration 7(a) Lending Act',
           'YEA-AND-NAY', 'PASSAGE', 'Passed', TRUE, NULL, 220, 200, 0, 0, 'http://x'),
          ('h-119-1-101', 119, 1, 'House', 101, DATE '2025-03-02',
           'On the Nomination', 'YEA-AND-NAY', 'NOMINATION', 'Confirmed', TRUE,
           NULL, 300, 100, 0, 0, 'http://x'),
          ('h-119-1-102', 119, 1, 'House', 102, DATE '2025-03-03',
           'Motion to Invoke Cloture', 'YEA-AND-NAY', 'CLOTURE', 'Agreed to', TRUE,
           NULL, 60, 40, 0, 0, 'http://x'),
          ('h-119-1-103', 119, 1, 'House', 103, DATE '2025-03-04',
           'On Passage of tariff and trade authority bill',
           'YEA-AND-NAY', 'PASSAGE', 'Passed', TRUE, 'hr-1-119', 210, 210, 0, 0, 'http://x')
        """
    )
    conn.execute(
        """
        INSERT INTO dim_bill (
            bill_id, congress, bill_type, bill_number, bill_number_raw,
            title, short_title, plain_language_summary, sponsor_bioguide,
            introduced_date, policy_area
        ) VALUES (
            'hr-1-119', 119, 'hr', 1, 'H.R. 1',
            'Trade and Tariff Act', NULL, NULL, NULL, NULL, 'Foreign Trade'
        )
        """
    )
    conn.close()
    return path


def test_rulebook_loads_all_seven_tags() -> None:
    book = load_rulebook()
    assert set(book.tag_patterns) == set(IMPACT_TAGS)


def test_sba_rule_fires_access_to_capital() -> None:
    book = load_rulebook()
    hits = classify_rules(
        vote_id="h-119-1-100",
        vote_category="PASSAGE",
        vote_question="On Passage of the Small Business Administration 7(a) Lending Act",
        title=None,
        short_title=None,
        policy_area=None,
        rulebook=book,
    )
    assert any(h.impact_tag == "ACCESS_TO_CAPITAL" for h in hits)
    assert all(h.confidence == 1.0 and h.classified_by == "RULE" for h in hits)


def test_cross_border_energy_does_not_false_match_workforce() -> None:
    """The WORKFORCE immigration pattern must not fire on "cross-border" energy
    bills (the bare `border` token used to false-match hr-3062)."""
    book = load_rulebook()
    hits = classify_rules(
        vote_id="h-119-1-277",
        vote_category="PASSAGE",
        vote_question="On Passage",
        title="Promoting Cross-border Energy Infrastructure Act",
        short_title=None,
        policy_area=None,
        rulebook=book,
    )
    assert not any(h.impact_tag == "WORKFORCE" for h in hits)


def test_border_security_still_matches_workforce() -> None:
    """Immigration-context border phrasing must still tag WORKFORCE."""
    book = load_rulebook()
    hits = classify_rules(
        vote_id="x",
        vote_category="PASSAGE",
        vote_question="On Passage of the Southern Border Security and Enforcement Act",
        title=None,
        short_title=None,
        policy_area=None,
        rulebook=book,
    )
    assert any(h.impact_tag == "WORKFORCE" for h in hits)


def test_policy_area_maps_to_tag_on_passage() -> None:
    """A Congress.gov policy_area of 'Energy' tags INPUT_COSTS even when the title
    text matches no pattern."""
    book = load_rulebook()
    hits = classify_rules(
        vote_id="h-119-1-324",
        vote_category="PASSAGE",
        vote_question="On Passage",
        title="Electric Supply Chain Act",  # no INPUT_COSTS regex hit on its own
        short_title=None,
        policy_area="Energy",
        rulebook=book,
    )
    assert any(h.impact_tag == "INPUT_COSTS" for h in hits)


def test_policy_area_not_applied_to_amendments() -> None:
    """policy_area is a bill attribute; amendment votes must not inherit it."""
    book = load_rulebook()
    hits = classify_rules(
        vote_id="h-119-1-246",
        vote_category="AMENDMENT",
        vote_question="On Agreeing to the Amendment",
        title="Some Defense Bill",
        short_title=None,
        policy_area="Energy",
        rulebook=book,
    )
    assert hits == []


def test_policy_area_deduplicates_with_regex() -> None:
    """A vote matching both a regex and its policy_area yields one tag, not two."""
    book = load_rulebook()
    hits = classify_rules(
        vote_id="x",
        vote_category="PASSAGE",
        vote_question="On Passage of a prescription drug pricing bill",  # HEALTH_COSTS regex
        title=None,
        short_title=None,
        policy_area="Health",  # also maps HEALTH_COSTS
        rulebook=book,
    )
    assert [h.impact_tag for h in hits].count("HEALTH_COSTS") == 1


def test_amendment_does_not_inherit_parent_bill_tag() -> None:
    """An amendment vote must not borrow the parent bill's tag from its title —
    an NDAA floor amendment shouldn't become FEDERAL_CONTRACTING because the bill
    is titled '...Procurement...' (hr-3838 amendments regression)."""
    book = load_rulebook()
    hits = classify_rules(
        vote_id="h-119-1-246",
        vote_category="AMENDMENT",
        vote_question="On Agreeing to the Amendment",
        title=(
            "Streamlining Procurement for Effective Execution and Delivery and "
            "National Defense Authorization Act for Fiscal Year 2026"
        ),
        short_title=None,
        policy_area="Armed Forces and National Security",
        rulebook=book,
    )
    assert hits == []


def test_passage_still_inherits_bill_tag() -> None:
    """The suppression is amendment-only: a PASSAGE vote still classifies on the
    bill title/policy_area as before."""
    book = load_rulebook()
    hits = classify_rules(
        vote_id="h-119-1-262",
        vote_category="PASSAGE",
        vote_question="On Passage",
        title="A Federal Procurement and Contracting Reform Act",
        short_title=None,
        policy_area=None,
        rulebook=book,
    )
    assert any(h.impact_tag == "FEDERAL_CONTRACTING" for h in hits)


def test_nomination_and_cloture_excluded() -> None:
    book = load_rulebook()
    for cat, q in (
        ("NOMINATION", "On the Nomination"),
        ("CLOTURE", "Motion to Invoke Cloture"),
    ):
        assert (
            classify_rules(
                vote_id="x",
                vote_category=cat,
                vote_question=q,
                title="SBA Administrator",
                short_title=None,
                policy_area=None,
                rulebook=book,
            )
            == []
        )


def test_classify_corpus_writes_rules_skips_personnel(warehouse: Path) -> None:
    stats = classify_corpus(
        warehouse_path=warehouse,
        enable_llm=False,
    )
    assert stats["excluded_personnel"] == 2
    assert stats["rule_tags_written"] >= 1
    conn = connect(warehouse)
    try:
        tags = conn.execute(
            "SELECT vote_id, impact_tag, classified_by FROM bridge_vote_impact ORDER BY 1, 2"
        ).fetchall()
        assert all(r[2] == "RULE" for r in tags)
        assert not any(r[0] in {"h-119-1-101", "h-119-1-102"} for r in tags)
        assert any(r[0] == "h-119-1-100" and r[1] == "ACCESS_TO_CAPITAL" for r in tags)
        assert any(r[0] == "h-119-1-103" and r[1] == "INPUT_COSTS" for r in tags)
    finally:
        conn.close()


def test_human_wins_on_promote(warehouse: Path, tmp_path: Path) -> None:
    classify_corpus(warehouse_path=warehouse, enable_llm=False)
    queue = tmp_path / "queue.csv"
    queue.write_text(
        "vote_id,impact_tag,confidence,classified_by,vote_question,title,"
        "queued_at_utc,human_decision\n"
        "h-119-1-100,TAX_BURDEN,0.5,LLM,q,t,2025-01-01,ACCEPT\n",
        encoding="utf-8",
    )
    assert promote_review_queue(queue_path=queue, warehouse_path=warehouse) == 1
    # RULE overwrite attempt should not clobber HUMAN
    conn = connect(warehouse)
    try:
        conn.execute(
            """
            INSERT INTO bridge_vote_impact AS t (vote_id, impact_tag, confidence, classified_by)
            VALUES ('h-119-1-100', 'TAX_BURDEN', 1.0, 'RULE')
            ON CONFLICT (vote_id, impact_tag) DO UPDATE SET
                confidence = CASE WHEN t.classified_by = 'HUMAN' THEN t.confidence
                                  ELSE excluded.confidence END,
                classified_by = CASE WHEN t.classified_by = 'HUMAN' THEN 'HUMAN'
                                     ELSE excluded.classified_by END
            """
        )
        row = conn.execute(
            """
            SELECT classified_by, confidence FROM bridge_vote_impact
            WHERE vote_id = 'h-119-1-100' AND impact_tag = 'TAX_BURDEN'
            """
        ).fetchone()
        assert row == ("HUMAN", 1.0)
    finally:
        conn.close()


def test_reclassify_requires_confirm(warehouse: Path) -> None:
    with pytest.raises(RuntimeError, match="--confirm"):
        reclassify_all(confirm=False, warehouse_path=warehouse)


def test_reclassify_writes_diff(warehouse: Path, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "vact.transforms.classify.REPORTS_DIR",
        tmp_path / "reports",
    )
    monkeypatch.setattr(
        "vact.transforms.classify.RECLASSIFY_DIFF_PATH",
        tmp_path / "reports" / "reclassify_diff.md",
    )
    classify_corpus(warehouse_path=warehouse, enable_llm=False)
    path = reclassify_all(confirm=True, warehouse_path=warehouse)
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "# Reclassify diff" in text
