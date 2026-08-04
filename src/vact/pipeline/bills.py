"""Bill-detail enrichment pipeline: fetch Congress.gov policy areas into dim_bill."""

from __future__ import annotations

from pathlib import Path

import structlog

from vact.http_client import create_client
from vact.sources import bills as bills_source
from vact.warehouse.connection import connect, ensure_schema
from vact.warehouse.load import enrich_dim_bill

logger = structlog.get_logger(__name__)


def _bills_needing_enrichment(conn, *, force: bool) -> list[tuple[str, int, str, int]]:
    """(bill_id, congress, bill_type, bill_number) for enrichable bills.

    Nominations (pn) have no bill endpoint. When not force, only bills missing a
    policy_area are fetched so the job is cheap and idempotent on re-run.
    """
    where = "bill_type <> 'pn' AND bill_number IS NOT NULL"
    if not force:
        where += " AND policy_area IS NULL"
    rows = conn.execute(
        f"SELECT bill_id, congress, bill_type, bill_number FROM dim_bill WHERE {where} "
        "ORDER BY congress, bill_type, bill_number"
    ).fetchall()
    return [(r[0], int(r[1]), r[2], int(r[3])) for r in rows]


def ingest_bills(
    *,
    api_key: str,
    warehouse_path: Path | None = None,
    force: bool = False,
    limit: int | None = None,
) -> dict[str, int]:
    """Enrich dim_bill with Congress.gov policy_area (+ sponsor/date). Idempotent.

    Fetches only bills missing a policy_area unless force. Raw JSON lands under
    data/raw/congress/. 404s are counted and skipped, not fatal.
    """
    conn = connect(warehouse_path)
    try:
        ensure_schema(conn)
        targets = _bills_needing_enrichment(conn, force=force)
        if limit is not None:
            targets = targets[:limit]

        enriched = with_policy_area = not_found = errors = 0
        with create_client(headers={"X-Api-Key": api_key}) as client:
            for bill_id, congress, bill_type, number in targets:
                try:
                    path = bills_source.fetch(
                        client, congress, bill_type, number, force=force
                    )
                    detail = bills_source.parse(path, bill_id)
                except bills_source.BillNotFound:
                    not_found += 1
                    continue
                except Exception as exc:  # noqa: BLE001 - one bad bill must not halt the run
                    errors += 1
                    logger.warning("bill_enrich_failed", bill_id=bill_id, error=str(exc))
                    continue
                enrich_dim_bill(detail, conn=conn)
                enriched += 1
                if detail.policy_area:
                    with_policy_area += 1

        return {
            "scanned": len(targets),
            "enriched": enriched,
            "with_policy_area": with_policy_area,
            "not_found": not_found,
            "errors": errors,
        }
    finally:
        conn.close()
