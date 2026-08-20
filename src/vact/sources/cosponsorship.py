"""Congress.gov member sponsored / cosponsored legislation.

fetch() writes unmodified list pages to disk; parse() reads only from disk
(AGENTS.md §2, §6). API key stays in the X-Api-Key header, never in the URL.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Sequence

import httpx
import structlog

from vact.http_client import get_with_retry
from vact.paths import raw_path
from vact.rate_limit import RateLimiter
from vact.sources.bills import API_BASE, SOURCE

logger = structlog.get_logger(__name__)

Kind = Literal["sponsored", "cosponsored"]
_DEFAULT_LIMITER = RateLimiter(4.0)
_TYPE_RE = re.compile(r"^[A-Za-z]+$")


@dataclass(frozen=True)
class BillRef:
    congress: int
    bill_type: str
    number: int
    title: str
    api_url: str

    @property
    def bill_id(self) -> str:
        return f"{self.bill_type}-{self.number}-{self.congress}"


def _norm_type(raw: str) -> str:
    text = (raw or "").strip().lower().replace(".", "").replace(" ", "")
    if not text or not _TYPE_RE.match(text):
        raise ValueError(f"unusable bill type {raw!r}")
    return text


def member_legislation_url(
    bioguide_id: str,
    kind: Kind,
    *,
    congress: int,
    offset: int = 0,
    limit: int = 250,
) -> str:
    slug = "sponsored-legislation" if kind == "sponsored" else "cosponsored-legislation"
    return f"{API_BASE}/member/{bioguide_id}/{slug}"


def raw_member_page_path(congress: int, bioguide_id: str, kind: Kind, offset: int) -> Path:
    ident = f"member-{bioguide_id}-{kind}-{offset}"
    return raw_path(SOURCE, congress, ident, "json")


def fetch_member_legislation(
    client: httpx.Client,
    bioguide_id: str,
    kind: Kind,
    *,
    congress: int,
    force: bool = False,
    page_size: int = 250,
    limiter: RateLimiter = _DEFAULT_LIMITER,
) -> list[Path]:
    """Page through one member list. Cached pages are reused unless force."""
    paths: list[Path] = []
    offset = 0
    while True:
        path = raw_member_page_path(congress, bioguide_id, kind, offset)
        if not path.exists() or force:
            limiter.wait()
            resp = get_with_retry(
                client,
                member_legislation_url(bioguide_id, kind, congress=congress),
                params={
                    "format": "json",
                    "congress": congress,
                    "limit": page_size,
                    "offset": offset,
                },
                allow_statuses={404},
            )
            if resp.status_code == 404:
                logger.warning("member_legislation_not_found", bioguide_id=bioguide_id, kind=kind)
                break
            resp.raise_for_status()
            path.write_text(resp.text, encoding="utf-8")
        paths.append(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        pagination = payload.get("pagination") or {}
        count = int(pagination.get("count") or 0)
        items = _items(payload)
        offset += page_size
        if not items or offset >= count:
            break
    return paths


def _items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("sponsoredLegislation", "cosponsoredLegislation"):
        val = payload.get(key)
        if isinstance(val, list):
            return val
    return []


def parse_member_legislation(paths: Sequence[Path]) -> list[BillRef]:
    """Parse cached pages into BillRef rows. Dedup by bill_id, first title wins."""
    out: dict[str, BillRef] = {}
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for rec in _items(payload):
            try:
                congress = int(rec.get("congress"))
                number = int(rec.get("number"))
                bill_type = _norm_type(str(rec.get("type") or rec.get("billType") or ""))
            except (TypeError, ValueError):
                continue
            title = str(rec.get("title") or "").strip()
            url = str(rec.get("url") or "")
            ref = BillRef(
                congress=congress,
                bill_type=bill_type,
                number=number,
                title=title,
                api_url=url,
            )
            out.setdefault(ref.bill_id, ref)
    return list(out.values())
