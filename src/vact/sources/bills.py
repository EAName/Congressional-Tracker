"""Congress.gov bill-detail ingest: policy area + sponsor/date enrichment.

fetch() writes the unmodified API JSON to disk; parse() reads only from disk
(AGENTS.md §2, §6). The API key travels as an X-Api-Key header, never in the URL,
so it cannot leak into retry logs. Nominations (pn) have no bill endpoint and are
skipped by the caller.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import structlog

from vact.http_client import get_with_retry
from vact.models.bills import BillDetail
from vact.paths import raw_path
from vact.rate_limit import RateLimiter

logger = structlog.get_logger(__name__)

SOURCE = "congress"
API_BASE = "https://api.congress.gov/v3"
MAX_REQUESTS_PER_SECOND = 4.0

_DEFAULT_LIMITER = RateLimiter(MAX_REQUESTS_PER_SECOND)


class BillNotFound(LookupError):
    """Raised when the Congress.gov API returns 404 for a bill."""


def bill_api_url(congress: int, bill_type: str, number: int) -> str:
    return f"{API_BASE}/bill/{congress}/{bill_type}/{number}?format=json"


def raw_bill_path(congress: int, bill_type: str, number: int) -> Path:
    return raw_path(SOURCE, congress, f"{bill_type}{number}", "json")


def fetch(
    client: httpx.Client,
    congress: int,
    bill_type: str,
    number: int,
    *,
    force: bool = False,
    limiter: RateLimiter = _DEFAULT_LIMITER,
) -> Path:
    """Fetch one bill's JSON to the raw landing zone; return the path.

    Cached: an existing raw file is reused unless force. Raises BillNotFound on 404.
    """
    path = raw_bill_path(congress, bill_type, number)
    if path.exists() and not force:
        return path
    limiter.wait()
    resp = get_with_retry(client, bill_api_url(congress, bill_type, number), allow_statuses={404})
    if resp.status_code == 404:
        raise BillNotFound(f"{bill_type}-{number}-{congress}")
    resp.raise_for_status()
    path.write_text(resp.text, encoding="utf-8")
    return path


def parse(path: Path, bill_id: str) -> BillDetail:
    """Parse a cached bill JSON into a BillDetail (policy area + sponsor/date)."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    bill = payload.get("bill") or {}
    policy_area = (bill.get("policyArea") or {}).get("name") or None
    sponsors = bill.get("sponsors") or []
    sponsor_bioguide = sponsors[0].get("bioguideId") if sponsors else None
    introduced = bill.get("introducedDate") or None
    return BillDetail(
        bill_id=bill_id,
        policy_area=policy_area,
        official_title=bill.get("title") or None,
        introduced_date=introduced,
        sponsor_bioguide=sponsor_bioguide,
    )
