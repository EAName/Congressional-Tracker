"""Challenger historical voting tests (Prompt 11)."""

from __future__ import annotations

from vact.analysis.challenger_historical import (
    build_head_to_head_payload,
    challenger_targets,
    era_caption,
    load_congress_terms,
    merge_review_queue,
)
from vact.analysis.votes import VoteRow


def test_challenger_targets_from_races() -> None:
    targets = challenger_targets()
    bios = {t["bioguide_id"] for t in targets}
    assert "L000791" in bios
    assert "P000601" in bios


def test_era_caption_two_congresses() -> None:
    text = era_caption([116, 117], load_congress_terms())
    assert "116" in text and "117" in text
    assert "indicative" in text


def test_review_queue_merge_preserves_adjudication() -> None:
    existing = [
        {
            "vote_id": "h-117-1-1",
            "vote_date": "2021-03-01",
            "adjudicated": "true",
            "suggested_theme": "FEDERAL_CONTRACTING",
        }
    ]
    proposed = [
        {
            "vote_id": "h-117-1-1",
            "vote_date": "2021-03-01",
            "adjudicated": "false",
            "suggested_theme": "OTHER",
        },
        {
            "vote_id": "h-117-1-2",
            "vote_date": "2021-03-02",
            "adjudicated": "false",
            "suggested_theme": "",
        },
    ]
    merged = merge_review_queue(proposed, existing)
    by_id = {r["vote_id"]: r for r in merged}
    assert by_id["h-117-1-1"]["adjudicated"] == "true"
    assert by_id["h-117-1-1"]["suggested_theme"] == "FEDERAL_CONTRACTING"
    assert "h-117-1-2" in by_id


def test_head_to_head_no_record_for_va01() -> None:
    payload = build_head_to_head_payload([])
    assert payload["races"]["va-01"]["status"] == "no_federal_record"


def test_head_to_head_with_adjudicated_historical(monkeypatch) -> None:
    from vact.analysis import challenger_historical as mod

    rows = [
        VoteRow.model_validate(
            {
                "member_bioguide_id": "L000791",
                "member_name": "Elaine Luria",
                "district": "2",
                "party": "Democrat",
                "congress": 117,
                "chamber": "House",
                "rollcall_id": "h-117-1-10",
                "rollcall_date": "2021-06-01",
                "bill_id": "",
                "theme": "FEDERAL_CONTRACTING",
                "axis_direction": "advance",
                "vote_cast": "yea",
                "contested": "true",
                "adjudicator": "HUMAN",
                "adjudication_date": "2026-08-19",
                "source_url": "http://clerk/h-117-1-10",
                "plain_language_summary": "",
                "coded_blind": "true",
                "congress_era": "117",
            }
        ),
        VoteRow.model_validate(
            {
                "member_bioguide_id": "D000001",
                "member_name": "Dem One",
                "district": "1",
                "party": "Democrat",
                "congress": 117,
                "chamber": "House",
                "rollcall_id": "h-117-1-10",
                "rollcall_date": "2021-06-01",
                "bill_id": "",
                "theme": "FEDERAL_CONTRACTING",
                "axis_direction": "advance",
                "vote_cast": "yea",
                "contested": "true",
                "adjudicator": "HUMAN",
                "adjudication_date": "2026-08-19",
                "source_url": "http://clerk/h-117-1-10",
                "plain_language_summary": "",
                "coded_blind": "true",
                "congress_era": "117",
            }
        ),
    ]
    monkeypatch.setattr(mod, "load_historical_candidates", lambda path=None: rows)
    incumbent_scores = [
        {
            "bioguide_id": "K000399",
            "full_name": "Jennifer Kiggans",
            "party": "Republican",
            "theme": "FEDERAL_CONTRACTING",
            "eb_score": 0.2,
            "cred_lo": -0.1,
            "cred_hi": 0.5,
            "n_contested": 4,
            "sufficient": True,
        }
    ]
    payload = build_head_to_head_payload(incumbent_scores)
    va02 = payload["races"]["va-02"]
    assert va02["status"] == "ready"
    assert va02["era_caption"]
    assert va02["themes"][0]["challenger"] is not None
