"""Senate LIS roll-call ingest.

fetch() writes unmodified XML to disk. parse() reads only from disk and
resolves lis_member_id → bioguide_id via the national crosswalk. Unresolved
LIS IDs raise UnresolvedLisMemberError (hard fail, never silent drop).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path

import httpx
import structlog

from vact.http_client import create_client, get_with_retry
from vact.models.senate_rollcalls import (
    SenateAmendmentRef,
    SenateDocumentRef,
    SenateMemberVoteRecord,
    SenateVoteRecord,
    SenateVoteTotals,
)
from vact.models.votes import normalize_vote_position
from vact.paths import raw_path
from vact.rate_limit import RateLimiter
from vact.transforms.lis_crosswalk import (
    UnresolvedLisMemberError,
    resolve_lis_member_id,
)

logger = structlog.get_logger(__name__)

SOURCE = "senate"
LIS_BASE = "https://www.senate.gov/legislative/LIS"
MAX_REQUESTS_PER_SECOND = 4.0

_DEFAULT_LIMITER = RateLimiter(MAX_REQUESTS_PER_SECOND)
_VOTE_DATE_FORMATS = (
    "%B %d, %Y,  %I:%M %p",
    "%B %d, %Y, %I:%M %p",
    "%B %d, %Y",
)


class SenateRollNotFound(LookupError):
    """Raised when senate.gov returns HTTP 404 for a roll call or menu."""


def menu_url(congress: int, session: int) -> str:
    return f"{LIS_BASE}/roll_call_lists/vote_menu_{congress}_{session}.xml"


def roll_url(congress: int, session: int, roll_number: int) -> str:
    return (
        f"{LIS_BASE}/roll_call_votes/vote{congress}{session}/"
        f"vote_{congress}_{session}_{roll_number:05d}.xml"
    )


def raw_menu_path(congress: int, session: int) -> Path:
    return raw_path(SOURCE, congress, f"vote_menu_{congress}_{session}", "xml")


def raw_roll_path(congress: int, session: int, roll_number: int) -> Path:
    year_key = f"{congress}_{session}"
    return raw_path(SOURCE, year_key, f"vote_{congress}_{session}_{roll_number:05d}", "xml")


def _text(node: ET.Element | None, tag: str) -> str | None:
    if node is None:
        return None
    child = node.find(tag)
    if child is None or child.text is None:
        return None
    value = child.text.strip()
    return value or None


def _int_or_zero(raw: str | None) -> int:
    if raw is None or not raw.strip():
        return 0
    return int(raw.strip())


def _parse_vote_date(raw: str | None) -> date:
    if not raw:
        raise ValueError("missing vote_date")
    cleaned = " ".join(raw.split())
    for fmt in _VOTE_DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    parts = cleaned.split(",")
    if len(parts) >= 2:
        date_part = f"{parts[0]},{parts[1]}".strip()
        return datetime.strptime(date_part, "%B %d, %Y").date()
    raise ValueError(f"unrecognized Senate vote_date: {raw!r}")


def _parse_document_or_nomination(root: ET.Element) -> SenateDocumentRef | None:
    nomination = root.find("nomination")
    if nomination is not None:
        return SenateDocumentRef(
            kind="nomination",
            congress=_int_or_none(_text(nomination, "nomination_congress")),
            document_type=_text(nomination, "nomination_type") or "PN",
            document_number=_text(nomination, "nomination_number"),
            name=_text(nomination, "nomination_name"),
            title=_text(nomination, "nomination_title")
            or _text(nomination, "nomination_description"),
            short_title=_text(nomination, "nomination_short_title"),
        )

    document = root.find("document")
    if document is None:
        return None
    return SenateDocumentRef(
        kind="document",
        congress=_int_or_none(_text(document, "document_congress")),
        document_type=_text(document, "document_type"),
        document_number=_text(document, "document_number"),
        name=_text(document, "document_name"),
        title=_text(document, "document_title"),
        short_title=_text(document, "document_short_title"),
    )


def _int_or_none(raw: str | None) -> int | None:
    if raw is None or not raw.strip():
        return None
    # document_number can be "11-18"; only parse pure integers here.
    if re.fullmatch(r"-?\d+", raw.strip()):
        return int(raw.strip())
    return None


def _parse_amendment(root: ET.Element) -> SenateAmendmentRef | None:
    amendment = root.find("amendment")
    if amendment is None:
        return None
    return SenateAmendmentRef(
        amendment_number=_text(amendment, "amendment_number"),
        amendment_to_amendment_number=_text(amendment, "amendment_to_amendment_number"),
        amendment_to_document_number=_text(amendment, "amendment_to_document_number"),
        amendment_purpose=_text(amendment, "amendment_purpose"),
    )


def _parse_totals(root: ET.Element) -> SenateVoteTotals:
    count = root.find("count")
    if count is None:
        raise ValueError("missing count block")
    return SenateVoteTotals(
        yea=_int_or_zero(_text(count, "yeas")),
        nay=_int_or_zero(_text(count, "nays")),
        present=_int_or_zero(_text(count, "present")),
        not_voting=_int_or_zero(_text(count, "absent")),
    )


def fetch_menu(
    congress: int,
    session: int,
    *,
    client: httpx.Client | None = None,
    force: bool = False,
    rate_limiter: RateLimiter | None = None,
) -> Path:
    """Download the Senate vote menu XML for a congress/session."""
    dest = raw_menu_path(congress, session)
    url = menu_url(congress, session)

    if dest.exists() and dest.stat().st_size > 0 and not force:
        logger.info(
            "senate_menu_fetch",
            congress=congress,
            session=session,
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
            "senate_menu_fetch",
            congress=congress,
            session=session,
            status_code=response.status_code,
            cache_hit=False,
            path=str(dest),
        )
        if response.status_code == 404:
            raise SenateRollNotFound(f"Senate menu {congress}/{session} not found")
        response.raise_for_status()
        dest.write_bytes(response.content)
        return dest
    finally:
        if owns_client:
            http.close()


def parse_menu(path: Path) -> set[int]:
    """Return the set of vote numbers listed in a Senate menu XML."""
    root = ET.fromstring(path.read_text(encoding="utf-8"))
    votes = root.find("votes")
    if votes is None:
        return set()
    numbers: set[int] = set()
    for vote in votes.findall("vote"):
        raw = _text(vote, "vote_number")
        if raw is None:
            continue
        numbers.add(int(raw))
    return numbers


def fetch(
    congress: int,
    session: int,
    roll_number: int,
    *,
    client: httpx.Client | None = None,
    force: bool = False,
    rate_limiter: RateLimiter | None = None,
) -> Path:
    """
    Download one Senate roll-call XML.

    Skips the network call when a non-empty cache file already exists unless
    force=True. Raises SenateRollNotFound on HTTP 404.
    """
    dest = raw_roll_path(congress, session, roll_number)
    url = roll_url(congress, session, roll_number)

    if dest.exists() and dest.stat().st_size > 0 and not force:
        logger.info(
            "senate_roll_fetch",
            congress=congress,
            session=session,
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
            "senate_roll_fetch",
            congress=congress,
            session=session,
            roll_number=roll_number,
            status_code=response.status_code,
            cache_hit=False,
            path=str(dest),
        )
        if response.status_code == 404:
            raise SenateRollNotFound(
                f"Senate roll {congress}/{session}/{roll_number:05d} not found"
            )
        response.raise_for_status()
        dest.write_bytes(response.content)
        return dest
    finally:
        if owns_client:
            http.close()


def parse(
    path: Path,
    *,
    lis_to_bioguide: Mapping[str, str],
) -> tuple[SenateVoteRecord, list[SenateMemberVoteRecord]]:
    """Parse a raw Senate roll-call XML file; resolve every lis_member_id."""
    if not path.exists():
        raise FileNotFoundError(path)

    root = ET.fromstring(path.read_text(encoding="utf-8"))
    if root.tag != "roll_call_vote":
        raise ValueError(f"unexpected root tag {root.tag!r} in {path}")

    congress = int(_text(root, "congress") or "0")
    session = int(_text(root, "session") or "0")
    roll_number = int(_text(root, "vote_number") or "0")
    congress_year = int(_text(root, "congress_year") or "0")

    vote = SenateVoteRecord(
        congress=congress,
        session=session,
        congress_year=congress_year,
        roll_number=roll_number,
        vote_date=_parse_vote_date(_text(root, "vote_date")),
        vote_question=_text(root, "question"),
        vote_question_text=_text(root, "vote_question_text"),
        vote_title=_text(root, "vote_title"),
        vote_result=_text(root, "vote_result"),
        vote_result_text=_text(root, "vote_result_text"),
        majority_requirement=_text(root, "majority_requirement"),
        document=_parse_document_or_nomination(root),
        amendment=_parse_amendment(root),
        totals=_parse_totals(root),
        source_url=roll_url(congress, session, roll_number),
    )

    members_node = root.find("members")
    if members_node is None:
        raise ValueError(f"missing members block in {path}")

    members: list[SenateMemberVoteRecord] = []
    unresolved: list[str] = []
    for member in members_node.findall("member"):
        lis_id = _text(member, "lis_member_id")
        if not lis_id:
            raise ValueError(f"member missing lis_member_id in {path}")
        try:
            bioguide = resolve_lis_member_id(lis_id, lis_to_bioguide)
        except UnresolvedLisMemberError:
            unresolved.append(lis_id)
            continue
        members.append(
            SenateMemberVoteRecord(
                bioguide_id=bioguide,
                lis_member_id=lis_id,
                name=_text(member, "member_full")
                or f"{_text(member, 'first_name')} {_text(member, 'last_name')}".strip(),
                party=_text(member, "party"),
                state=_text(member, "state"),
                position=normalize_vote_position(_text(member, "vote_cast")),
            )
        )

    if unresolved:
        raise UnresolvedLisMemberError(unresolved)

    return vote, members


def discover(
    congress: int,
    session: int,
    *,
    client: httpx.Client | None = None,
    force: bool = False,
    rate_limiter: RateLimiter | None = None,
) -> set[int]:
    """Return vote numbers for a congress/session from the Senate menu XML."""
    owns_client = client is None
    http = client or create_client()
    try:
        path = fetch_menu(
            congress,
            session,
            client=http,
            force=force,
            rate_limiter=rate_limiter,
        )
        return parse_menu(path)
    finally:
        if owns_client:
            http.close()
