"""House Clerk EVS ingest contract tests."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from vact.models.votes import VotePosition, normalize_vote_position
from vact.rate_limit import RateLimiter
from vact.sources import house_rollcalls as house

SAMPLE_YEA_NAY = """<?xml version="1.0" encoding="UTF-8"?>
<rollcall-vote>
  <vote-metadata>
    <majority>R</majority>
    <congress>119</congress>
    <session>1st</session>
    <chamber>U.S. House of Representatives</chamber>
    <rollcall-num>156</rollcall-num>
    <legis-num>H R 2966</legis-num>
    <vote-question>On Passage</vote-question>
    <vote-type>YEA-AND-NAY</vote-type>
    <vote-result>Passed</vote-result>
    <action-date>6-Jun-2025</action-date>
    <action-time time-etz="10:15">10:15 AM</action-time>
    <vote-desc>American Entrepreneurs First Act</vote-desc>
    <vote-totals>
      <totals-by-vote>
        <total-stub>Totals</total-stub>
        <yea-total>2</yea-total>
        <nay-total>1</nay-total>
        <present-total>0</present-total>
        <not-voting-total>1</not-voting-total>
      </totals-by-vote>
    </vote-totals>
  </vote-metadata>
  <vote-data>
    <recorded-vote>
      <legislator name-id="W000804" sort-field="Wittman" unaccented-name="Wittman"
        party="R" state="VA" role="legislator">Wittman</legislator>
      <vote>Yea</vote>
    </recorded-vote>
    <recorded-vote>
      <legislator name-id="B001292" sort-field="Beyer" unaccented-name="Beyer"
        party="D" state="VA" role="legislator">Beyer</legislator>
      <vote>Nay</vote>
    </recorded-vote>
    <recorded-vote>
      <legislator name-id="K000399" sort-field="Kiggans" unaccented-name="Kiggans"
        party="R" state="VA" role="legislator">Kiggans</legislator>
      <vote>Yea</vote>
    </recorded-vote>
    <recorded-vote>
      <legislator name-id="S000185" sort-field="Scott" unaccented-name="Scott"
        party="D" state="VA" role="legislator">Scott</legislator>
      <vote>Not Voting</vote>
    </recorded-vote>
  </vote-data>
</rollcall-vote>
"""

SAMPLE_AYE_NO = """<?xml version="1.0" encoding="UTF-8"?>
<rollcall-vote>
  <vote-metadata>
    <majority>R</majority>
    <congress>119</congress>
    <session>1st</session>
    <committee>U.S. House of Representatives</committee>
    <rollcall-num>180</rollcall-num>
    <legis-num>H R 3944</legis-num>
    <vote-question>On Agreeing to the Amendment</vote-question>
    <amendment-num>2</amendment-num>
    <amendment-author>Carter of Texas Amendment En Bloc No. 2</amendment-author>
    <vote-type>RECORDED VOTE</vote-type>
    <vote-result>Agreed to</vote-result>
    <action-date>25-Jun-2025</action-date>
    <action-time>4:53 PM</action-time>
    <vote-desc></vote-desc>
    <vote-totals>
      <totals-by-vote>
        <total-stub>Totals</total-stub>
        <yea-total>1</yea-total>
        <nay-total>1</nay-total>
        <present-total>1</present-total>
        <not-voting-total>0</not-voting-total>
      </totals-by-vote>
    </vote-totals>
  </vote-metadata>
  <vote-data>
    <recorded-vote>
      <legislator name-id="W000804" unaccented-name="Wittman" party="R" state="VA" role="legislator">Wittman</legislator>
      <vote>Aye</vote>
    </recorded-vote>
    <recorded-vote>
      <legislator name-id="B001292" unaccented-name="Beyer" party="D" state="VA" role="legislator">Beyer</legislator>
      <vote>No</vote>
    </recorded-vote>
    <recorded-vote>
      <legislator name-id="K000399" unaccented-name="Kiggans" party="R" state="VA" role="legislator">Kiggans</legislator>
      <vote>Present</vote>
    </recorded-vote>
  </vote-data>
</rollcall-vote>
"""


@pytest.fixture()
def patch_raw(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    def _raw_roll_path(year: int, roll_number: int) -> Path:
        path = tmp_path / "house" / str(year) / f"roll{roll_number:03d}.xml"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    monkeypatch.setattr(house, "raw_roll_path", _raw_roll_path)
    return tmp_path


def test_normalize_aye_no() -> None:
    assert normalize_vote_position("Aye") is VotePosition.YEA
    assert normalize_vote_position("No") is VotePosition.NAY
    assert normalize_vote_position("Yea") is VotePosition.YEA
    assert normalize_vote_position("Not Voting") is VotePosition.NOT_VOTING


def test_parse_yea_nay(tmp_path: Path) -> None:
    path = tmp_path / "2025" / "roll156.xml"
    path.parent.mkdir(parents=True)
    path.write_text(SAMPLE_YEA_NAY, encoding="utf-8")
    vote, members = house.parse(path)
    assert vote.roll_number == 156
    assert vote.action_date.isoformat() == "2025-06-06"
    assert vote.session == 1
    assert vote.totals.yea == 2
    assert {m.bioguide_id: m.position for m in members}["W000804"] is VotePosition.YEA
    assert {m.bioguide_id: m.position for m in members}["S000185"] is VotePosition.NOT_VOTING


def test_parse_aye_no_committee_of_the_whole(tmp_path: Path) -> None:
    path = tmp_path / "2025" / "roll180.xml"
    path.parent.mkdir(parents=True)
    path.write_text(SAMPLE_AYE_NO, encoding="utf-8")
    vote, members = house.parse(path)
    assert vote.chamber.startswith("U.S. House")
    assert vote.amendment_num == "2"
    by_id = {m.bioguide_id: m.position for m in members}
    assert by_id["W000804"] is VotePosition.YEA
    assert by_id["B001292"] is VotePosition.NAY
    assert by_id["K000399"] is VotePosition.PRESENT


def test_fetch_cache_hit_skips_network(
    patch_raw: Path,
    httpx_mock,
) -> None:
    path = house.raw_roll_path(2025, 156)
    path.write_text(SAMPLE_YEA_NAY, encoding="utf-8")
    result = house.fetch(2025, 156, rate_limiter=RateLimiter(1000))
    assert result == path
    assert httpx_mock.get_requests() == []


def test_fetch_writes_on_200(patch_raw: Path, httpx_mock) -> None:
    httpx_mock.add_response(
        url=house.roll_url(2025, 156),
        method="GET",
        status_code=200,
        text=SAMPLE_YEA_NAY,
    )
    client = httpx.Client()
    path = house.fetch(2025, 156, client=client, rate_limiter=RateLimiter(1000))
    client.close()
    assert path.exists()
    assert path.read_text(encoding="utf-8") == SAMPLE_YEA_NAY


def test_fetch_404_raises(patch_raw: Path, httpx_mock) -> None:
    httpx_mock.add_response(
        url=house.roll_url(2025, 999),
        method="GET",
        status_code=404,
        text="not found",
    )
    client = httpx.Client()
    with pytest.raises(house.HouseRollNotFound):
        house.fetch(2025, 999, client=client, rate_limiter=RateLimiter(1000))
    client.close()


def test_discover_stops_after_five_404s(patch_raw: Path, httpx_mock) -> None:
    # rolls 1-2 exist; 3-7 are 404 → stop; must not request 8+
    for n in (1, 2):
        httpx_mock.add_response(
            url=house.roll_url(2025, n),
            method="GET",
            status_code=200,
            text=SAMPLE_YEA_NAY.replace(">156<", f">{n}<").replace("roll156", f"roll{n:03d}"),
        )
    for n in range(3, 8):
        httpx_mock.add_response(
            url=house.roll_url(2025, n),
            method="GET",
            status_code=404,
            text="missing",
        )

    client = httpx.Client()
    found = house.discover(2025, client=client, rate_limiter=RateLimiter(1000))
    client.close()
    assert found == {1, 2}
    requested = [req.url.path for req in httpx_mock.get_requests()]
    assert requested == [
        "/evs/2025/roll001.xml",
        "/evs/2025/roll002.xml",
        "/evs/2025/roll003.xml",
        "/evs/2025/roll004.xml",
        "/evs/2025/roll005.xml",
        "/evs/2025/roll006.xml",
        "/evs/2025/roll007.xml",
    ]
