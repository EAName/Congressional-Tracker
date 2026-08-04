"""Tests for Virginia 2021/2026 district map crosswalk."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from vact.models.legislators import DimLegislatorRow
from vact.transforms.districts import (
    TARGET_DISTRICTS_2026,
    attach_map_districts,
    build_dim_district_rows,
    load_district_specs,
    require_map_version,
)
from vact.warehouse.connection import connect, ensure_schema
from vact.warehouse.load import upsert_dim_district, upsert_dim_legislator


def test_dim_district_shape() -> None:
    rows = build_dim_district_rows()
    assert len(rows) == 22
    assert {(r.district_number, r.map_version) for r in rows} == {
        (d, m) for d in range(1, 12) for m in ("2021", "2026")
    }


def test_2026_targets_are_exactly_four() -> None:
    rows = build_dim_district_rows()
    targets_2026 = {
        r.district_number for r in rows if r.map_version == "2026" and r.is_target
    }
    targets_2021 = {
        r.district_number for r in rows if r.map_version == "2021" and r.is_target
    }
    assert targets_2026 == TARGET_DISTRICTS_2026 == {1, 2, 5, 6}
    assert targets_2021 == set()


def test_attach_map_districts_house_and_senate() -> None:
    house = DimLegislatorRow(
        bioguide_id="W000804",
        full_name="Robert J. Wittman",
        chamber="House",
        state="VA",
        district_current=1,
        party="Republican",
        term_start=date(2025, 1, 3),
        term_end=date(2027, 1, 3),
        first_elected=2007,
        is_incumbent=True,
    )
    senate = DimLegislatorRow(
        bioguide_id="W000805",
        full_name="Mark R. Warner",
        chamber="Senate",
        state="VA",
        district_current=None,
        party="Democrat",
        term_start=date(2021, 1, 3),
        term_end=date(2027, 1, 3),
        first_elected=2009,
        is_incumbent=True,
    )
    attached = attach_map_districts([house, senate])
    assert attached[0].district_2025 == 1
    assert attached[0].district_2026 == 1  # numbering persists; geo differs in dim_district
    assert attached[1].district_2025 is None
    assert attached[1].district_2026 is None


def test_require_map_version() -> None:
    assert require_map_version("2021") == "2021"
    with pytest.raises(ValueError, match="map_version"):
        require_map_version("2010")


def test_upsert_dim_district(tmp_path: Path) -> None:
    path = tmp_path / "warehouse.duckdb"
    rows = build_dim_district_rows()
    assert upsert_dim_district(rows, warehouse_path=path) == 22
    assert upsert_dim_district(rows, warehouse_path=path) == 22  # idempotent
    conn = connect(path)
    try:
        ensure_schema(conn)
        n = conn.execute("SELECT COUNT(*) FROM dim_district").fetchone()[0]
        assert n == 22
        targets = conn.execute(
            """
            SELECT district_number FROM dim_district
            WHERE map_version = '2026' AND is_target
            ORDER BY 1
            """
        ).fetchall()
        assert [r[0] for r in targets] == [1, 2, 5, 6]
    finally:
        conn.close()


def test_config_incumbents_match_targets() -> None:
    specs = load_district_specs()
    by_key = {(s.district_number, s.map_version): s for s in specs}
    assert by_key[(1, "2026")].incumbent_bioguide == "W000804"  # Wittman
    assert by_key[(2, "2026")].incumbent_bioguide == "K000399"  # Kiggans
    assert by_key[(5, "2026")].incumbent_bioguide == "M001239"  # McGuire
    assert by_key[(6, "2026")].incumbent_bioguide == "C001118"  # Cline
