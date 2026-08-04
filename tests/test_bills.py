"""Tests for Congress.gov bill-detail ingest (policy_area enrichment)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from vact.http_client import create_client
from vact.pipeline import bills as bills_pipeline
from vact.sources import bills as bills_source
from vact.warehouse.connection import connect, ensure_schema
from vact.warehouse.load import enrich_dim_bill

SAMPLE = {
    "bill": {
        "policyArea": {"name": "Commerce"},
        "title": "American Entrepreneurs First Act of 2025",
        "introducedDate": "2025-04-17",
        "sponsors": [{"bioguideId": "V000134", "party": "R"}],
    }
}


@pytest.fixture()
def patch_raw(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    def _raw_bill_path(congress: int, bill_type: str, number: int) -> Path:
        path = tmp_path / "congress" / str(congress) / f"{bill_type}{number}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    monkeypatch.setattr(bills_source, "raw_bill_path", _raw_bill_path)
    return tmp_path


def _seed_bill(path: Path, bill_id: str, bill_type: str, number: int) -> None:
    conn = connect(path)
    ensure_schema(conn)
    conn.execute(
        "INSERT INTO dim_bill (bill_id, congress, bill_type, bill_number, title) "
        "VALUES (?, 119, ?, ?, 'Roll-call derived title')",
        [bill_id, bill_type, number],
    )
    conn.close()


def test_parse_extracts_policy_area(tmp_path: Path) -> None:
    raw = tmp_path / "hr2966.json"
    raw.write_text(json.dumps(SAMPLE), encoding="utf-8")
    detail = bills_source.parse(raw, "hr-2966-119")
    assert detail.policy_area == "Commerce"
    assert detail.sponsor_bioguide == "V000134"
    assert detail.introduced_date == date(2025, 4, 17)


def test_parse_tolerates_missing_policy_area(tmp_path: Path) -> None:
    raw = tmp_path / "x.json"
    raw.write_text(json.dumps({"bill": {"title": "Something"}}), encoding="utf-8")
    detail = bills_source.parse(raw, "hr-1-119")
    assert detail.policy_area is None
    assert detail.sponsor_bioguide is None


def test_fetch_writes_on_200(patch_raw: Path, httpx_mock) -> None:
    httpx_mock.add_response(
        url=bills_source.bill_api_url(119, "hr", 2966), json=SAMPLE, status_code=200
    )
    client = create_client(headers={"X-Api-Key": "test"})
    from vact.rate_limit import RateLimiter

    path = bills_source.fetch(client, 119, "hr", 2966, limiter=RateLimiter(1000))
    assert path.exists()
    assert bills_source.parse(path, "hr-2966-119").policy_area == "Commerce"


def test_fetch_cache_hit_skips_network(patch_raw: Path, httpx_mock) -> None:
    cached = bills_source.raw_bill_path(119, "hr", 2966)
    cached.write_text(json.dumps(SAMPLE), encoding="utf-8")
    from vact.rate_limit import RateLimiter

    client = create_client(headers={"X-Api-Key": "test"})
    path = bills_source.fetch(client, 119, "hr", 2966, limiter=RateLimiter(1000))
    assert path == cached
    assert httpx_mock.get_requests() == []


def test_fetch_404_raises(patch_raw: Path, httpx_mock) -> None:
    httpx_mock.add_response(url=bills_source.bill_api_url(119, "hr", 999), status_code=404)
    from vact.rate_limit import RateLimiter

    client = create_client(headers={"X-Api-Key": "test"})
    with pytest.raises(bills_source.BillNotFound):
        bills_source.fetch(client, 119, "hr", 999, limiter=RateLimiter(1000))


def test_enrich_sets_policy_area_without_clobbering_title(tmp_path: Path) -> None:
    wh = tmp_path / "w.duckdb"
    _seed_bill(wh, "hr-2966-119", "hr", 2966)
    from vact.models.bills import BillDetail

    conn = connect(wh)
    try:
        enrich_dim_bill(BillDetail(bill_id="hr-2966-119", policy_area="Commerce"), conn=conn)
        row = conn.execute(
            "SELECT policy_area, title FROM dim_bill WHERE bill_id = 'hr-2966-119'"
        ).fetchone()
    finally:
        conn.close()
    assert row == ("Commerce", "Roll-call derived title")


def test_pipeline_enriches_and_is_idempotent(patch_raw: Path, tmp_path: Path, httpx_mock) -> None:
    wh = tmp_path / "w.duckdb"
    _seed_bill(wh, "hr-2966-119", "hr", 2966)
    # Nominations must be skipped (no bill endpoint).
    conn = connect(wh)
    conn.execute(
        "INSERT INTO dim_bill (bill_id, congress, bill_type, bill_number, bill_number_raw, title) "
        "VALUES ('pn-11-18-119', 119, 'pn', NULL, '11-18', 'A nomination')"
    )
    conn.close()

    httpx_mock.add_response(
        url=bills_source.bill_api_url(119, "hr", 2966), json=SAMPLE, status_code=200
    )
    stats = bills_pipeline.ingest_bills(api_key="test", warehouse_path=wh)
    assert stats["scanned"] == 1  # only the hr bill; pn excluded
    assert stats["with_policy_area"] == 1

    # Second run: policy_area already set → nothing to scan (idempotent, cached).
    stats2 = bills_pipeline.ingest_bills(api_key="test", warehouse_path=wh)
    assert stats2["scanned"] == 0
