"""Notification policy: pipeline failures vs outreach party-line splits."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import structlog

from vact.exports.data import SITE_SUPPRESSED_CATEGORIES
from vact.paths import DATA_DIR

logger = structlog.get_logger(__name__)

REPORTS_DIR = DATA_DIR / "reports"
OUTREACH_SIGNAL_PATH = REPORTS_DIR / "outreach_signals.jsonl"

PIPELINE_WEBHOOK_ENV = "VACT_NOTIFY_PIPELINE_WEBHOOK"
OUTREACH_WEBHOOK_ENV = "VACT_NOTIFY_OUTREACH_WEBHOOK"


@dataclass(frozen=True)
class OutreachSignal:
    vote_id: str
    vote_date: str
    vote_category: str
    tags: list[str]
    dem_position: str
    gop_position: str
    source_url: str | None
    kind: str = "party_line_split"


def _normalize_party(party: str | None) -> str | None:
    if party is None:
        return None
    p = party.strip().lower()
    if p.startswith("dem"):
        return "Democrat"
    if p.startswith("rep"):
        return "Republican"
    return None


def find_party_line_splits(
    conn,
    *,
    vote_ids: list[str] | None = None,
) -> list[OutreachSignal]:
    """
    Votes where VA Democrats and Republicans each vote unanimously YEA/NAY
    and disagree; must have a RULE/HUMAN impact tag and not be suppressed.
    """
    suppressed = sorted(SITE_SUPPRESSED_CATEGORIES)
    sup_ph = ", ".join("?" for _ in suppressed)

    if vote_ids is not None:
        if not vote_ids:
            return []
        vote_ph = ", ".join("?" for _ in vote_ids)
        vote_clause = f"AND v.vote_id IN ({vote_ph})"
        params: list[Any] = [*vote_ids, *suppressed]
    else:
        vote_clause = ""
        params = list(suppressed)

    detail = conn.execute(
        f"""
        SELECT
            v.vote_id,
            cast(v.vote_date AS VARCHAR),
            v.vote_category,
            v.source_url,
            m.position,
            l.party
        FROM fact_vote v
        JOIN fact_member_vote m ON m.vote_id = v.vote_id
        JOIN dim_legislator l
          ON l.bioguide_id = m.bioguide_id
         AND l.term_start <= v.vote_date
         AND v.vote_date < l.term_end
        WHERE l.state = 'VA'
          AND m.position IN ('YEA', 'NAY')
          AND v.vote_category NOT IN ({sup_ph})
          {vote_clause}
          AND EXISTS (
              SELECT 1 FROM bridge_vote_impact i
              WHERE i.vote_id = v.vote_id
                AND i.classified_by IN ('RULE', 'HUMAN')
          )
        """,
        params,
    ).fetchall()

    by_vote: dict[str, dict[str, Any]] = {}
    for vote_id, vote_date, category, source_url, position, party in detail:
        bucket = by_vote.setdefault(
            vote_id,
            {
                "vote_date": vote_date,
                "vote_category": category,
                "source_url": source_url,
                "by_party": {},
            },
        )
        norm = _normalize_party(party)
        if norm is None:
            continue
        bucket["by_party"].setdefault(norm, set()).add(position)

    tag_rows = conn.execute(
        """
        SELECT vote_id, list(DISTINCT impact_tag ORDER BY impact_tag)
        FROM bridge_vote_impact
        WHERE classified_by IN ('RULE', 'HUMAN')
        GROUP BY 1
        """
    ).fetchall()
    tags_by_vote = {r[0]: list(r[1] or []) for r in tag_rows}

    signals: list[OutreachSignal] = []
    for vote_id, meta in by_vote.items():
        dem = meta["by_party"].get("Democrat")
        gop = meta["by_party"].get("Republican")
        if not dem or not gop:
            continue
        if len(dem) != 1 or len(gop) != 1:
            continue
        dem_pos = next(iter(dem))
        gop_pos = next(iter(gop))
        if dem_pos == gop_pos:
            continue
        tags = tags_by_vote.get(vote_id) or []
        if not tags:
            continue
        signals.append(
            OutreachSignal(
                vote_id=vote_id,
                vote_date=str(meta["vote_date"]),
                vote_category=str(meta["vote_category"]),
                tags=tags,
                dem_position=dem_pos,
                gop_position=gop_pos,
                source_url=meta["source_url"],
            )
        )
    signals.sort(key=lambda s: (s.vote_date, s.vote_id), reverse=True)
    return signals


def append_outreach_signals(signals: list[OutreachSignal]) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    with OUTREACH_SIGNAL_PATH.open("a", encoding="utf-8") as fh:
        for signal in signals:
            payload = asdict(signal)
            payload["recorded_at_utc"] = datetime.now(UTC).isoformat()
            fh.write(json.dumps(payload, sort_keys=True) + "\n")
    return OUTREACH_SIGNAL_PATH


def post_webhook(url: str, payload: dict[str, Any]) -> None:
    with httpx.Client(timeout=20.0) as client:
        resp = client.post(url, json=payload)
        resp.raise_for_status()


def notify_pipeline_failure(summary: str, *, details: dict[str, Any] | None = None) -> None:
    """Channel (a): contract / pipeline failures only."""
    url = os.environ.get(PIPELINE_WEBHOOK_ENV)
    payload = {
        "channel": "pipeline",
        "summary": summary,
        "details": details or {},
        "at": datetime.now(UTC).isoformat(),
    }
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / "pipeline_alerts.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, sort_keys=True) + "\n")
    if not url:
        logger.info("pipeline_notify_local_only", path=str(path))
        return
    post_webhook(url, payload)


def notify_outreach(signals: list[OutreachSignal]) -> None:
    """Channel (b): party-line splits on tagged substantive votes — phone-worthy."""
    if not signals:
        return
    append_outreach_signals(signals)
    url = os.environ.get(OUTREACH_WEBHOOK_ENV)
    payload = {
        "channel": "outreach",
        "count": len(signals),
        "signals": [asdict(s) for s in signals[:20]],
        "at": datetime.now(UTC).isoformat(),
    }
    if not url:
        logger.info(
            "outreach_notify_local_only",
            path=str(OUTREACH_SIGNAL_PATH),
            count=len(signals),
        )
        return
    post_webhook(url, payload)
