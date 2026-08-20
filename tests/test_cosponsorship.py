"""Cosponsorship candidate ingest and separate EB scores (Prompt 6)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vact.analysis.bills_candidates import (
    BillCandidate,
    merge_candidates,
    propose_from_bills,
    validate_candidates,
)
from vact.analysis.cosponsorship import build_cosponsor_frame, merge_actions
from vact.analysis.estimators import estimate_member_theme, fit_caucus_prior
from vact.analysis.scoring import load_scoring_config
from vact.http_client import create_client
from vact.rate_limit import RateLimiter
from vact.sources.cosponsorship import (
    BillRef,
    fetch_member_legislation,
    parse_member_legislation,
)
from vact.transforms.classify import tags_for_corpus


def test_sba_title_is_tagged() -> None:
    tags = tags_for_corpus(title="To reauthorize the SBA 7(a) lending program")
    assert "ACCESS_TO_CAPITAL" in tags


def test_parse_member_legislation_pages(tmp_path: Path) -> None:
    page = tmp_path / "p0.json"
    page.write_text(
        json.dumps(
            {
                "pagination": {"count": 1},
                "sponsoredLegislation": [
                    {
                        "congress": 119,
                        "type": "HR",
                        "number": 7,
                        "title": "SBA 7(a) expansion",
                        "url": "https://api.congress.gov/v3/bill/119/hr/7",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    refs = parse_member_legislation([page])
    assert len(refs) == 1
    assert refs[0].bill_id == "hr-7-119"


def test_fetch_is_cached(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, httpx_mock) -> None:
    def _path(congress: int, bioguide_id: str, kind: str, offset: int) -> Path:
        return tmp_path / f"{bioguide_id}-{kind}-{offset}.json"

    monkeypatch.setattr("vact.sources.cosponsorship.raw_member_page_path", _path)
    payload = {
        "pagination": {"count": 1},
        "sponsoredLegislation": [
            {"congress": 119, "type": "HR", "number": 1, "title": "A", "url": ""}
        ],
    }
    httpx_mock.add_response(method="GET", json=payload)
    client = create_client(headers={"X-Api-Key": "test"})
    paths = fetch_member_legislation(
        client, "B001292", "sponsored", congress=119, limiter=RateLimiter(1000)
    )
    assert paths[0].exists()
    fetch_member_legislation(
        client, "B001292", "sponsored", congress=119, limiter=RateLimiter(1000)
    )
    assert len(httpx_mock.get_requests()) == 1


def test_human_rows_not_overwritten() -> None:
    human = BillCandidate(
        bill_id="hr-1-119",
        congress=119,
        bill_type="hr",
        bill_number=1,
        title="Keep me",
        theme="TAX_BURDEN",
        axis_direction="advance",
        adjudicated=True,
        adjudicator="HUMAN",
    )
    incoming = BillCandidate(
        bill_id="hr-1-119",
        congress=119,
        bill_type="hr",
        bill_number=1,
        title="Overwrite attempt",
        theme="TAX_BURDEN",
        axis_direction="oppose",
        adjudicated=False,
        adjudicator="RULE",
    )
    merged = merge_candidates([human], [incoming])
    assert merged[0].title == "Keep me"
    assert merged[0].adjudicated is True


def test_cosponsor_score_reuses_estimator_and_is_not_a_vote_average() -> None:
    cfg = load_scoring_config()
    cands = [
        BillCandidate(
            bill_id="hr-1-119",
            congress=119,
            bill_type="hr",
            bill_number=1,
            title="t",
            theme="TAX_BURDEN",
            axis_direction="advance",
            adjudicated=True,
            adjudicator="HUMAN",
        ),
        BillCandidate(
            bill_id="hr-2-119",
            congress=119,
            bill_type="hr",
            bill_number=2,
            title="t",
            theme="TAX_BURDEN",
            axis_direction="oppose",
            adjudicated=True,
            adjudicator="HUMAN",
        ),
        BillCandidate(
            bill_id="hr-3-119",
            congress=119,
            bill_type="hr",
            bill_number=3,
            title="t",
            theme="TAX_BURDEN",
            axis_direction="advance",
            adjudicated=True,
            adjudicator="HUMAN",
        ),
    ]
    members = {
        "A": {
            "bioguide_id": "A",
            "full_name": "A",
            "party": "Democrat",
            "chamber": "House",
            "district_number": 1,
        },
        "B": {
            "bioguide_id": "B",
            "full_name": "B",
            "party": "Democrat",
            "chamber": "House",
            "district_number": 2,
        },
        "C": {
            "bioguide_id": "C",
            "full_name": "C",
            "party": "Democrat",
            "chamber": "House",
            "district_number": 3,
        },
    }
    actions = [
        {"member_bioguide_id": "A", "bill_id": "hr-1-119", "role": "sponsor"},
        {"member_bioguide_id": "A", "bill_id": "hr-2-119", "role": "cosponsor"},
        {"member_bioguide_id": "A", "bill_id": "hr-3-119", "role": "cosponsor"},
        {"member_bioguide_id": "B", "bill_id": "hr-1-119", "role": "cosponsor"},
        {"member_bioguide_id": "B", "bill_id": "hr-3-119", "role": "cosponsor"},
        {"member_bioguide_id": "C", "bill_id": "hr-2-119", "role": "sponsor"},
    ]
    frame = build_cosponsor_frame(cands, actions, members, cfg)
    by_id = {r["bioguide_id"]: r for r in frame}
    assert by_id["A"]["k"] == 2 and by_id["A"]["n"] == 3
    assert by_id["C"]["k"] == 0 and by_id["C"]["n"] == 1
    prior = fit_caucus_prior(
        [by_id[m]["k"] for m in "ABC"],
        [by_id[m]["n"] for m in "ABC"],
        method=cfg.eb_method,
        min_caucus=cfg.eb_min_caucus,
        fallback_alpha=cfg.eb_fallback_alpha,
        fallback_beta=cfg.eb_fallback_beta,
    )
    direct = estimate_member_theme(2, 3, prior, wilson_z=cfg.wilson_z)
    assert by_id["A"]["eb_score"] == direct.eb_score
    assert by_id["A"]["n"] == 3


def test_sponsor_wins_merge() -> None:
    merged = merge_actions(
        [{"member_bioguide_id": "A", "bill_id": "hr-1-119", "role": "cosponsor"}],
        [{"member_bioguide_id": "A", "bill_id": "hr-1-119", "role": "sponsor"}],
    )
    assert len(merged) == 1
    assert merged[0]["role"] == "sponsor"


def test_unadjudicated_bills_do_not_score() -> None:
    cands = [
        BillCandidate(
            bill_id="hr-9-119",
            congress=119,
            bill_type="hr",
            bill_number=9,
            title="t",
            theme="TAX_BURDEN",
            axis_direction="advance",
            adjudicated=False,
            adjudicator="RULE",
        )
    ]
    frame = build_cosponsor_frame(
        cands,
        [{"member_bioguide_id": "A", "bill_id": "hr-9-119", "role": "sponsor"}],
        {
            "A": {
                "bioguide_id": "A",
                "full_name": "A",
                "party": "Democrat",
                "chamber": "House",
                "district_number": 1,
            }
        },
        load_scoring_config(),
    )
    assert frame == []


def test_propose_requires_rule_hit() -> None:
    bills = [
        BillRef(congress=119, bill_type="hr", number=1, title="Designating a post office", api_url=""),
        BillRef(congress=119, bill_type="hr", number=2, title="SBA 7(a) loan limit increase", api_url=""),
    ]
    rows = propose_from_bills(bills)
    assert all(r.adjudicated is False for r in rows)
    assert any(r.bill_id == "hr-2-119" for r in rows)
    assert all(r.bill_id != "hr-1-119" for r in rows)
    assert validate_candidates(rows) == []
