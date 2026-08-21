"""OpenFEC campaign-finance fetch/parse (Prompt 10).

fetch() writes unmodified JSON under data/raw/fec/; parse() reads only from disk
(AGENTS.md §2, §6). API key travels as a query param required by OpenFEC; never
log the key.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import structlog

from vact.http_client import get_with_retry
from vact.paths import raw_path
from vact.rate_limit import RateLimiter

logger = structlog.get_logger(__name__)

SOURCE = "fec"
API_BASE = "https://api.open.fec.gov/v1"
# OpenFEC DEMO_KEY is ~120/hr; paid keys tolerate more. Default stays polite.
_DEFAULT_LIMITER = RateLimiter(0.5)


def _write_empty_payload(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"results": [], "pagination": {"count": 0}}, indent=2), encoding="utf-8")
    return path


def totals_url(candidate_id: str) -> str:
    return f"{API_BASE}/candidate/{candidate_id}/totals/"


def ie_by_candidate_url() -> str:
    return f"{API_BASE}/schedules/schedule_e/by_candidate/"


def raw_totals_path(cycle: int, candidate_id: str, snapshot_day: str) -> Path:
    return raw_path(SOURCE, cycle, f"{candidate_id}-totals-{snapshot_day}", "json")


def raw_ie_path(cycle: int, candidate_id: str, snapshot_day: str) -> Path:
    return raw_path(SOURCE, cycle, f"{candidate_id}-ie-{snapshot_day}", "json")


def fetch_candidate_totals(
    client: httpx.Client,
    candidate_id: str,
    *,
    cycle: int,
    api_key: str,
    snapshot_day: str,
    force: bool = False,
    limiter: RateLimiter = _DEFAULT_LIMITER,
) -> Path:
    path = raw_totals_path(cycle, candidate_id, snapshot_day)
    if path.exists() and not force:
        return path
    limiter.wait()
    try:
        resp = get_with_retry(
            client,
            totals_url(candidate_id),
            params={"api_key": api_key, "cycle": cycle, "per_page": 20},
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as err:
        if err.response.status_code == 429:
            logger.warning("fec.totals_rate_limited", candidate_id=candidate_id)
            return _write_empty_payload(path)
        raise
    path.write_text(resp.text, encoding="utf-8")
    return path


def fetch_ie_by_candidate(
    client: httpx.Client,
    candidate_id: str,
    *,
    cycle: int,
    api_key: str,
    snapshot_day: str,
    force: bool = False,
    limiter: RateLimiter = _DEFAULT_LIMITER,
) -> Path:
    path = raw_ie_path(cycle, candidate_id, snapshot_day)
    if path.exists() and not force:
        return path
    limiter.wait()
    try:
        resp = get_with_retry(
            client,
            ie_by_candidate_url(),
            params={
                "api_key": api_key,
                "candidate_id": candidate_id,
                "cycle": cycle,
                "per_page": 100,
            },
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as err:
        # IE is secondary to receipts; rate-limit should not block the snapshot.
        if err.response.status_code == 429:
            logger.warning("fec.ie_rate_limited", candidate_id=candidate_id)
            return _write_empty_payload(path)
        raise
    path.write_text(resp.text, encoding="utf-8")
    return path


def parse_totals(path: Path, *, cycle: int) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    results = payload.get("results") or []
    row = next((r for r in results if int(r.get("cycle") or 0) == cycle), None)
    if row is None and results:
        row = results[0]
    if row is None:
        return {
            "receipts": None,
            "cash_on_hand": None,
            "individual_contributions": None,
            "individual_unitemized_contributions": None,
            "small_dollar_share": None,
            "coverage_end_date": None,
        }
    individual = float(row.get("individual_contributions") or 0.0)
    unitemized = float(row.get("individual_unitemized_contributions") or 0.0)
    share = (unitemized / individual) if individual > 0 else None
    return {
        "receipts": float(row.get("receipts") or 0.0),
        "cash_on_hand": float(row.get("last_cash_on_hand_end_period") or 0.0),
        "individual_contributions": individual,
        "individual_unitemized_contributions": unitemized,
        "small_dollar_share": None if share is None else round(share, 4),
        "coverage_end_date": (row.get("coverage_end_date") or "")[:10] or None,
    }


def parse_ie(path: Path) -> dict[str, float]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    support = 0.0
    oppose = 0.0
    for row in payload.get("results") or []:
        total = float(row.get("total") or 0.0)
        flag = str(row.get("support_oppose_indicator") or "").upper()
        if flag == "S":
            support += total
        elif flag == "O":
            oppose += total
    return {
        "independent_expenditures_support": round(support, 2),
        "independent_expenditures_oppose": round(oppose, 2),
    }
