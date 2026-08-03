"""House Clerk Electronic Voting System roll-call ingest.

fetch() writes unmodified XML to disk. parse() reads only from disk.
discover() walks roll numbers for a year and treats HTTP 404 as terminal.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import date, datetime
from pathlib import Path

import httpx
import structlog

from vact.http_client import create_client, get_with_retry
from vact.models.house_rollcalls import (
    HouseMemberVoteRecord,
    HouseVoteRecord,
    HouseVoteTotals,
)
from vact.models.votes import normalize_vote_position
from vact.paths import raw_path
from vact.rate_limit import RateLimiter

logger = structlog.get_logger(__name__)

SOURCE = "house"
EVS_BASE = "https://clerk.house.gov/evs"
MAX_REQUESTS_PER_SECOND = 4.0
DISCOVER_STOP_AFTER_404S = 5

_SESSION_RE = re.compile(r"(\d+)")
_DEFAULT_LIMITER = RateLimiter(MAX_REQUESTS_PER_SECOND)


class HouseRollNotFound(LookupError):
    """Raised when the Clerk returns HTTP 404 for a roll call."""


def roll_url(year: int, roll_number: int) -> str:
    return f"{EVS_BASE}/{year}/roll{roll_number:03d}.xml"


def raw_roll_path(year: int, roll_number: int) -> Path:
    return raw_path(SOURCE, year, f"roll{roll_number:03d}", "xml")


def _text(node: ET.Element | None, tag: str) -> str | None:
    if node is None:
        return None
    child = node.find(tag)
    if child is None or child.text is None:
        return None
    value = child.text.strip()
    return value or None


def _parse_session(raw: str | None) -> int:
    if not raw:
        raise ValueError("missing session in vote-metadata")
    match = _SESSION_RE.search(raw)
    if not match:
        raise ValueError(f"unrecognized session label: {raw!r}")
    return int(match.group(1))


def _parse_action_date(raw: str | None) -> date:
    if not raw:
        raise ValueError("missing action-date")
    return datetime.strptime(raw.strip(), "%d-%b-%Y").date()


def _parse_totals(meta: ET.Element) -> HouseVoteTotals:
    totals_block = meta.find("vote-totals")
    if totals_block is None:
        raise ValueError("missing vote-totals")
    by_vote = totals_block.find("totals-by-vote")
    if by_vote is None:
        raise ValueError("missing totals-by-vote")
    return HouseVoteTotals(
        yea=int(_text(by_vote, "yea-total") or "0"),
        nay=int(_text(by_vote, "nay-total") or "0"),
        present=int(_text(by_vote, "present-total") or "0"),
        not_voting=int(_text(by_vote, "not-voting-total") or "0"),
    )


def fetch(
    year: int,
    roll_number: int,
    *,
    client: httpx.Client | None = None,
    force: bool = False,
    rate_limiter: RateLimiter | None = None,
) -> Path:
    """
    Download one House roll-call XML into data/raw/house/{year}/roll{NNN}.xml.

    Skips the network call when a non-empty cache file already exists unless
    force=True. Raises HouseRollNotFound on HTTP 404.
    """
    dest = raw_roll_path(year, roll_number)
    url = roll_url(year, roll_number)

    if dest.exists() and dest.stat().st_size > 0 and not force:
        logger.info(
            "house_roll_fetch",
            year=year,
            roll_number=roll_number,
            status_code=None,
            cache_hit=True,
            path=str(dest),
        )
        return dest

    owns_client = client is None
    http = client or create_client()
    limiter = rate_limiter or _DEFAULT_LIMITER
    try:
        limiter.wait()
        response = get_with_retry(http, url, allow_statuses={404})
        logger.info(
            "house_roll_fetch",
            year=year,
            roll_number=roll_number,
            status_code=response.status_code,
            cache_hit=False,
            path=str(dest),
        )
        if response.status_code == 404:
            raise HouseRollNotFound(f"House roll {year}/{roll_number:03d} not found")
        response.raise_for_status()
        dest.write_bytes(response.content)
        return dest
    finally:
        if owns_client:
            http.close()


def parse(path: Path) -> tuple[HouseVoteRecord, list[HouseMemberVoteRecord]]:
    """Parse a raw House EVS XML file from disk."""
    if not path.exists():
        raise FileNotFoundError(path)

    # Filename is roll{NNN}.xml under .../{year}/
    year = int(path.parent.name)
    roll_from_name = int(path.stem.replace("roll", ""))

    root = ET.fromstring(path.read_text(encoding="utf-8"))
    if root.tag != "rollcall-vote":
        raise ValueError(f"unexpected root tag {root.tag!r} in {path}")

    meta = root.find("vote-metadata")
    if meta is None:
        raise ValueError(f"missing vote-metadata in {path}")

    roll_number = int(_text(meta, "rollcall-num") or roll_from_name)
    chamber = _text(meta, "chamber") or _text(meta, "committee") or "U.S. House of Representatives"
    url = roll_url(year, roll_number)

    vote = HouseVoteRecord(
        year=year,
        congress=int(_text(meta, "congress") or "0"),
        session=_parse_session(_text(meta, "session")),
        chamber=chamber,
        roll_number=roll_number,
        legis_num=_text(meta, "legis-num"),
        vote_question=_text(meta, "vote-question"),
        vote_type=_text(meta, "vote-type"),
        vote_result=_text(meta, "vote-result"),
        action_date=_parse_action_date(_text(meta, "action-date")),
        action_time=_text(meta, "action-time"),
        vote_desc=_text(meta, "vote-desc"),
        majority=_text(meta, "majority"),
        amendment_num=_text(meta, "amendment-num"),
        amendment_author=_text(meta, "amendment-author"),
        totals=_parse_totals(meta),
        source_url=url,
    )

    vote_data = root.find("vote-data")
    if vote_data is None:
        raise ValueError(f"missing vote-data in {path}")

    members: list[HouseMemberVoteRecord] = []
    for recorded in vote_data.findall("recorded-vote"):
        legislator = recorded.find("legislator")
        position_node = recorded.find("vote")
        if legislator is None or position_node is None:
            raise ValueError(f"malformed recorded-vote in {path}")
        bioguide = legislator.attrib.get("name-id")
        if not bioguide:
            raise ValueError(f"recorded-vote missing name-id (bioguide) in {path}")
        members.append(
            HouseMemberVoteRecord(
                bioguide_id=bioguide,
                name=legislator.attrib.get("unaccented-name")
                or (legislator.text or "").strip()
                or bioguide,
                party=legislator.attrib.get("party"),
                state=legislator.attrib.get("state"),
                role=legislator.attrib.get("role"),
                position=normalize_vote_position(position_node.text),
            )
        )

    return vote, members


def discover(
    year: int,
    *,
    client: httpx.Client | None = None,
    start: int = 1,
    rate_limiter: RateLimiter | None = None,
    force: bool = False,
) -> set[int]:
    """
    Walk roll numbers for a year and return the set of valid rolls.

    HTTP 404 is terminal for that roll number (not retried). Discovery stops
    after `DISCOVER_STOP_AFTER_404S` consecutive 404s above the highest known
    valid roll.
    """
    if start < 1:
        raise ValueError("start must be >= 1")

    owns_client = client is None
    http = client or create_client()
    limiter = rate_limiter or _DEFAULT_LIMITER
    valid: set[int] = set()
    consecutive_404 = 0
    roll_number = start

    try:
        while True:
            try:
                fetch(
                    year,
                    roll_number,
                    client=http,
                    force=force,
                    rate_limiter=limiter,
                )
            except HouseRollNotFound:
                consecutive_404 += 1
                highest = max(valid) if valid else 0
                logger.info(
                    "house_roll_discover_404",
                    year=year,
                    roll_number=roll_number,
                    consecutive_404=consecutive_404,
                    highest_valid=highest,
                )
                if consecutive_404 >= DISCOVER_STOP_AFTER_404S and roll_number > highest:
                    break
            else:
                consecutive_404 = 0
                valid.add(roll_number)
            roll_number += 1
        return valid
    finally:
        if owns_client:
            http.close()
