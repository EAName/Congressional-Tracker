"""Dimension refresh with upstream SHA gating and VA delegation alerts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx
import structlog

from vact.http_client import create_client, get_with_retry
from vact.sources import legislators as legislator_source
from vact.transforms.districts import build_dim_district_rows
from vact.transforms.legislators import build_dim_legislator_rows
from vact.warehouse.connection import connect, ensure_schema
from vact.warehouse.load import upsert_dim_district, upsert_dim_legislator
from vact.warehouse.meta import (
    META_DELEGATION_FP,
    META_LEGISLATORS_SHA,
    get_meta,
    set_meta,
)

logger = structlog.get_logger(__name__)

GITHUB_COMMITS_URL = (
    "https://api.github.com/repos/unitedstates/congress-legislators/commits"
)


@dataclass(frozen=True)
class DimensionsResult:
    upstream_sha: str
    previous_sha: str | None
    changed: bool
    skipped: bool
    legislator_rows: int
    district_rows: int
    delegation_changed: bool
    previous_delegation_fp: str | None
    delegation_fp: str


def fetch_upstream_legislators_sha(*, client: httpx.Client | None = None) -> str:
    """Latest commit SHA on unitedstates/congress-legislators main."""
    owns = client is None
    http = client or create_client(
        headers={"Accept": "application/vnd.github+json"}
    )
    try:
        resp = get_with_retry(http, f"{GITHUB_COMMITS_URL}?per_page=1")
        resp.raise_for_status()
        payload = resp.json()
        if not payload:
            raise RuntimeError("empty commits list from congress-legislators")
        sha = payload[0]["sha"]
        if not isinstance(sha, str) or len(sha) < 7:
            raise RuntimeError(f"unexpected commit SHA payload: {sha!r}")
        return sha
    finally:
        if owns:
            http.close()


def delegation_fingerprint(conn) -> str:
    rows = conn.execute(
        """
        SELECT bioguide_id, chamber, coalesce(district_current, -1), party,
               term_start, term_end, is_incumbent
        FROM dim_legislator
        ORDER BY bioguide_id, term_start
        """
    ).fetchall()
    return ";".join("|".join(str(c) for c in r) for r in rows)


def refresh_dimensions(
    *,
    force: bool = False,
    warehouse_path: Path | None = None,
) -> DimensionsResult:
    """
    Fetch congress-legislators when upstream SHA changes (or --force).

    Always alerts (delegation_changed=True) when the VA SCD2 fingerprint moves,
    even if tests pass — a seat change is news before it is a data issue.
    """
    upstream = fetch_upstream_legislators_sha()
    conn = connect(warehouse_path)
    try:
        ensure_schema(conn)
        previous = get_meta(conn, META_LEGISLATORS_SHA)
        prev_fp = get_meta(conn, META_DELEGATION_FP)

        if not force and previous == upstream:
            logger.info(
                "dimensions_skip_unchanged",
                sha=upstream,
            )
            fp = delegation_fingerprint(conn)
            return DimensionsResult(
                upstream_sha=upstream,
                previous_sha=previous,
                changed=False,
                skipped=True,
                legislator_rows=0,
                district_rows=0,
                delegation_changed=False,
                previous_delegation_fp=prev_fp,
                delegation_fp=fp,
            )

        paths = legislator_source.fetch_all(force=True)
        records = legislator_source.parse_legislators(
            paths["legislators-current"]
        ) + legislator_source.parse_legislators(paths["legislators-historical"])
        legislator_source.parse_district_offices(
            paths["legislators-district-offices"]
        )
        rows = build_dim_legislator_rows(records)
        n_leg = upsert_dim_legislator(rows, conn=conn)
        n_dist = upsert_dim_district(build_dim_district_rows(), conn=conn)

        fp = delegation_fingerprint(conn)
        set_meta(conn, META_LEGISLATORS_SHA, upstream)
        set_meta(conn, META_DELEGATION_FP, fp)
        delegation_changed = prev_fp is not None and prev_fp != fp

        logger.info(
            "dimensions_refreshed",
            sha=upstream,
            previous_sha=previous,
            legislator_rows=n_leg,
            district_rows=n_dist,
            delegation_changed=delegation_changed,
        )
        return DimensionsResult(
            upstream_sha=upstream,
            previous_sha=previous,
            changed=True,
            skipped=False,
            legislator_rows=n_leg,
            district_rows=n_dist,
            delegation_changed=delegation_changed,
            previous_delegation_fp=prev_fp,
            delegation_fp=fp,
        )
    finally:
        conn.close()
