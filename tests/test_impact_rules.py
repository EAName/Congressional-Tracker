"""Impact rulebook recall and precision guards (rulebook v2)."""

from __future__ import annotations

import csv

from vact.transforms.classify import load_rulebook, tags_for_corpus

SCOREABLE = {"PASSAGE", "AMENDMENT"}
REVIEW = "data/historical_rollcall_review.csv"


def _tag(title: str) -> str:
    tags = tags_for_corpus(title=title, rulebook=load_rulebook())
    return tags[0] if tags else ""


def test_marquee_small_business_bills_are_matched() -> None:
    """v1 matched jargon (SBA, 7(a), HUBZone) but missed plain-English titles,
    which is how it lost the 111th Congress's biggest relevant votes."""
    for title, expect in (
        ("Hiring Incentives to Restore Employment Act", "TAX_BURDEN"),
        ("Small Business Jobs Act of 2010", "ACCESS_TO_CAPITAL"),
        ("Lilly Ledbetter Fair Pay Act of 2009", "WORKFORCE"),
        ("Wall Street Reform and Consumer Protection Act of 2009", "REGULATORY_BURDEN"),
        ("American Clean Energy and Security Act", "INPUT_COSTS"),
    ):
        assert _tag(title) == expect, f"{title!r} tagged {_tag(title)!r}, expected {expect}"


def test_consumer_credit_is_not_small_business_credit() -> None:
    """Deliberately unmatched. The Expedited CARD Reform for Consumers Act came up
    in sampling as a plausible ACCESS_TO_CAPITAL miss, but it governs consumer
    credit cards. Widening a pattern to reach it would cost precision on a
    marginal case."""
    assert _tag("Expedited CARD Reform for Consumers Act of 2009") == ""


def test_defense_procurement_is_not_small_business_contracting() -> None:
    """Bare 'acquisition reform' pulled in the Weapon Systems Acquisition Reform
    Act, which has no small-business contracting content."""
    assert _tag("Weapon Systems Acquisition Reform Act") == ""


def test_legacy_jargon_still_matches() -> None:
    """Widening must not regress what v1 already caught."""
    for title, expect in (
        ("A bill to reauthorize the SBA 7(a) loan program", "ACCESS_TO_CAPITAL"),
        ("HUBZone set-aside improvements", "FEDERAL_CONTRACTING"),
        ("Paperwork Reduction and Regulatory Flexibility improvements", "REGULATORY_BURDEN"),
    ):
        assert _tag(title) == expect, f"{title!r} regressed to {_tag(title)!r}"


def test_recall_lifted_on_the_111th_without_inflating_the_others() -> None:
    """The lift must come from real coverage, not from a pattern loose enough to
    match anything. 116th/117th were already well covered and should barely move."""
    rows = [r for r in csv.DictReader(open(REVIEW, encoding="utf-8"))
            if r["vote_category"] in SCOREABLE]
    if not rows:
        return  # queue not built in this environment
    rates = {}
    for era in ("111", "116", "117"):
        era_rows = [r for r in rows if r["congress_era"] == era]
        if not era_rows:
            continue
        tagged = sum(1 for r in era_rows if _tag(r["title"] or ""))
        rates[era] = tagged / len(era_rows)
    if "111" in rates:
        assert rates["111"] > 0.10, f"111th recall fell back to {rates['111']:.3f}"
    for era in ("116", "117"):
        if era in rates:
            assert rates[era] < 0.15, f"{era} recall {rates[era]:.3f} looks like over-matching"
