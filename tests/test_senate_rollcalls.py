"""Senate LIS ingest contract tests."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from vact.models.legislators import LegislatorIds, LegislatorName, LegislatorRecord
from vact.models.votes import VotePosition
from vact.rate_limit import RateLimiter
from vact.sources import senate_rollcalls as senate
from vact.transforms.lis_crosswalk import (
    AmbiguousLisMappingError,
    UnresolvedLisMemberError,
    build_lis_bioguide_crosswalk,
)

SAMPLE_MENU = """<?xml version="1.0" encoding="UTF-8"?>
<vote_summary>
  <congress>119</congress>
  <session>1</session>
  <congress_year>2025</congress_year>
  <votes>
    <vote><vote_number>00059</vote_number></vote>
    <vote><vote_number>00318</vote_number></vote>
  </votes>
</vote_summary>
"""

SAMPLE_PASSAGE = """<?xml version="1.0" encoding="UTF-8"?>
<roll_call_vote>
  <congress>119</congress>
  <session>1</session>
  <congress_year>2025</congress_year>
  <vote_number>318</vote_number>
  <vote_date>June 17, 2025,  05:11 PM</vote_date>
  <vote_question_text>On Passage of the Bill S. 1582</vote_question_text>
  <vote_document_text>A bill to provide for regulation.</vote_document_text>
  <vote_result_text>Bill Passed (2-1)</vote_result_text>
  <question>On Passage of the Bill</question>
  <vote_title>S. 1582, As Amended</vote_title>
  <majority_requirement>1/2</majority_requirement>
  <vote_result>Bill Passed</vote_result>
  <document>
    <document_congress>119</document_congress>
    <document_type>S.</document_type>
    <document_number>1582</document_number>
    <document_name>S. 1582</document_name>
    <document_title>A bill to provide for regulation.</document_title>
    <document_short_title/>
  </document>
  <amendment>
    <amendment_number>2307</amendment_number>
    <amendment_to_amendment_number/>
    <amendment_to_document_number>S. 1582</amendment_to_document_number>
    <amendment_purpose>In the nature of a substitute.</amendment_purpose>
  </amendment>
  <count>
    <yeas>2</yeas>
    <nays>1</nays>
    <present/>
    <absent>0</absent>
  </count>
  <members>
    <member>
      <member_full>Warner (D-VA)</member_full>
      <party>D</party><state>VA</state>
      <vote_cast>Yea</vote_cast>
      <lis_member_id>S327</lis_member_id>
    </member>
    <member>
      <member_full>Kaine (D-VA)</member_full>
      <party>D</party><state>VA</state>
      <vote_cast>Nay</vote_cast>
      <lis_member_id>S362</lis_member_id>
    </member>
    <member>
      <member_full>Other (R-TX)</member_full>
      <party>R</party><state>TX</state>
      <vote_cast>Yea</vote_cast>
      <lis_member_id>S999</lis_member_id>
    </member>
  </members>
</roll_call_vote>
"""

SAMPLE_NOMINATION_BRANCH = """<?xml version="1.0" encoding="UTF-8"?>
<roll_call_vote>
  <congress>119</congress>
  <session>1</session>
  <congress_year>2025</congress_year>
  <vote_number>59</vote_number>
  <vote_date>February 19, 2025,  11:59 AM</vote_date>
  <vote_question_text>On the Nomination PN11-18</vote_question_text>
  <question>On the Nomination</question>
  <vote_title>Confirmation: Kelly Loeffler</vote_title>
  <vote_result>Nomination Confirmed</vote_result>
  <vote_result_text>Nomination Confirmed (1-0)</vote_result_text>
  <nomination>
    <nomination_congress>119</nomination_congress>
    <nomination_type>PN</nomination_type>
    <nomination_number>11-18</nomination_number>
    <nomination_name>PN11-18</nomination_name>
    <nomination_title>Kelly Loeffler, of Georgia, to be Administrator of the SBA</nomination_title>
  </nomination>
  <count><yeas>1</yeas><nays>0</nays><present/><absent>0</absent></count>
  <members>
    <member>
      <member_full>Warner (D-VA)</member_full>
      <party>D</party><state>VA</state>
      <vote_cast>Yea</vote_cast>
      <lis_member_id>S327</lis_member_id>
    </member>
  </members>
</roll_call_vote>
"""


def _crosswalk() -> dict[str, str]:
    return {
        "S327": "W000805",
        "S362": "K000384",
        "S999": "X000001",
    }


@pytest.fixture()
def patch_raw(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    def _raw_roll_path(congress: int, session: int, roll_number: int) -> Path:
        path = (
            tmp_path
            / "senate"
            / f"{congress}_{session}"
            / f"vote_{congress}_{session}_{roll_number:05d}.xml"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _raw_menu_path(congress: int, session: int) -> Path:
        path = tmp_path / "senate" / str(congress) / f"vote_menu_{congress}_{session}.xml"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    monkeypatch.setattr(senate, "raw_roll_path", _raw_roll_path)
    monkeypatch.setattr(senate, "raw_menu_path", _raw_menu_path)
    return tmp_path


def test_build_lis_crosswalk_detects_ambiguity() -> None:
    records = [
        LegislatorRecord(
            id=LegislatorIds(bioguide="A000001", lis="S001"),
            name=LegislatorName(official_full="A"),
            terms=[],
        ),
        LegislatorRecord(
            id=LegislatorIds(bioguide="B000001", lis="S001"),
            name=LegislatorName(official_full="B"),
            terms=[],
        ),
    ]
    with pytest.raises(AmbiguousLisMappingError):
        build_lis_bioguide_crosswalk(records)


def test_parse_passage_resolves_lis(tmp_path: Path) -> None:
    path = tmp_path / "vote.xml"
    path.write_text(SAMPLE_PASSAGE, encoding="utf-8")
    vote, members = senate.parse(path, lis_to_bioguide=_crosswalk())
    assert vote.roll_number == 318
    assert vote.vote_date.isoformat() == "2025-06-17"
    assert vote.document is not None and vote.document.kind == "document"
    assert vote.amendment is not None and vote.amendment.amendment_number == "2307"
    by_lis = {m.lis_member_id: m for m in members}
    assert by_lis["S327"].bioguide_id == "W000805"
    assert by_lis["S327"].position is VotePosition.YEA
    assert by_lis["S362"].position is VotePosition.NAY


def test_parse_nomination_branch(tmp_path: Path) -> None:
    path = tmp_path / "nom.xml"
    path.write_text(SAMPLE_NOMINATION_BRANCH, encoding="utf-8")
    vote, members = senate.parse(path, lis_to_bioguide=_crosswalk())
    assert vote.document is not None
    assert vote.document.kind == "nomination"
    assert vote.document.document_number == "11-18"
    assert members[0].bioguide_id == "W000805"


def test_parse_unresolved_lis_hard_fails(tmp_path: Path) -> None:
    path = tmp_path / "vote.xml"
    path.write_text(SAMPLE_PASSAGE, encoding="utf-8")
    with pytest.raises(UnresolvedLisMemberError) as exc:
        senate.parse(path, lis_to_bioguide={"S327": "W000805", "S362": "K000384"})
    assert "S999" in exc.value.unresolved


def test_fetch_cache_hit(patch_raw: Path, httpx_mock) -> None:
    path = senate.raw_roll_path(119, 1, 318)
    path.write_text(SAMPLE_PASSAGE, encoding="utf-8")
    result = senate.fetch(119, 1, 318, rate_limiter=RateLimiter(1000))
    assert result == path
    assert httpx_mock.get_requests() == []


def test_fetch_and_discover_menu(patch_raw: Path, httpx_mock) -> None:
    httpx_mock.add_response(
        url=senate.menu_url(119, 1),
        method="GET",
        status_code=200,
        text=SAMPLE_MENU,
    )
    httpx_mock.add_response(
        url=senate.roll_url(119, 1, 59),
        method="GET",
        status_code=200,
        text=SAMPLE_NOMINATION_BRANCH,
    )
    client = httpx.Client()
    found = senate.discover(119, 1, client=client, rate_limiter=RateLimiter(1000))
    path = senate.fetch(119, 1, 59, client=client, rate_limiter=RateLimiter(1000))
    client.close()
    assert found == {59, 318}
    vote, _ = senate.parse(path, lis_to_bioguide=_crosswalk())
    assert vote.roll_number == 59
