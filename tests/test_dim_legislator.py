"""Virginia dim_legislator coverage and schema contracts."""

from __future__ import annotations

from datetime import date, timedelta
import pytest

from vact.constants import CONGRESS_119_START
from vact.sources import legislators as legislator_source
from vact.transforms.legislators import build_dim_legislator_rows
from vact.warehouse.connection import connect
from vact.warehouse.load import upsert_dim_legislator

# Gerald Connolly died in office; Walkinshaw seated after the 2025-09-09 special.
VA11_PREDECESSOR = "C001078"
VA11_SUCCESSOR = "W000831"
ALLOWED_VACANCY = {
    11: (date(2025, 5, 21), date(2025, 9, 10)),
}


@pytest.fixture(scope="module")
def legislator_paths(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """Fetch once into the project raw landing zone (cached on disk)."""
    return legislator_source.fetch_all(force=False)


@pytest.fixture(scope="module")
def dim_rows(legislator_paths: dict[str, Path]):
    current = legislator_source.parse_legislators(
        legislator_paths["legislators-current"]
    )
    historical = legislator_source.parse_legislators(
        legislator_paths["legislators-historical"]
    )
    # Ensure district offices parse; Prompt 1 requires the fetch/parse contract.
    offices = legislator_source.parse_district_offices(
        legislator_paths["legislators-district-offices"]
    )
    assert offices, "district offices payload should not be empty"
    return build_dim_legislator_rows(current + historical, as_of=date.today())


@pytest.fixture(scope="module")
def warehouse_conn(tmp_path_factory: pytest.TempPathFactory, dim_rows):
    path = tmp_path_factory.mktemp("warehouse") / "test.duckdb"
    n = upsert_dim_legislator(dim_rows, warehouse_path=path)
    assert n == len(dim_rows)
    conn = connect(path)
    yield conn
    conn.close()


def test_virginia_delegation_shape(dim_rows) -> None:
    senators = [r for r in dim_rows if r.chamber == "Senate"]
    house = [r for r in dim_rows if r.chamber == "House"]

    assert len({r.bioguide_id for r in senators}) == 2
    assert {r.district_current for r in house} == set(range(1, 12))

    # SCD2: VA-11 has predecessor and Walkinshaw, not a permanent vacant.
    va11 = [r for r in house if r.district_current == 11]
    bioguides = {r.bioguide_id for r in va11}
    assert VA11_PREDECESSOR in bioguides
    assert VA11_SUCCESSOR in bioguides
    walkinshaw = next(r for r in va11 if r.bioguide_id == VA11_SUCCESSOR)
    assert walkinshaw.term_start == date(2025, 9, 10)


def test_natural_keys_unique(dim_rows) -> None:
    keys = [(r.bioguide_id, r.term_start) for r in dim_rows]
    assert len(keys) == len(set(keys))


def test_first_elected_not_conflated_with_bioguide(dim_rows) -> None:
    for row in dim_rows:
        assert 1900 <= row.first_elected <= date.today().year
        assert row.bioguide_id[0].isalpha()
        assert not row.bioguide_id.isdigit()


def test_upsert_idempotent(warehouse_conn, dim_rows) -> None:
    before = warehouse_conn.execute("SELECT COUNT(*) FROM dim_legislator").fetchone()[0]
    upsert_dim_legislator(dim_rows, conn=warehouse_conn)
    after = warehouse_conn.execute("SELECT COUNT(*) FROM dim_legislator").fetchone()[0]
    assert before == after == len(dim_rows)


def _seat_covers_day(rows, chamber: str, district: int | None, day: date) -> bool:
    for row in rows:
        if row.chamber != chamber:
            continue
        if chamber == "House" and row.district_current != district:
            continue
        if row.term_start <= day < row.term_end:
            return True
    return False


def _day_in_allowed_vacancy(district: int, day: date) -> bool:
    window = ALLOWED_VACANCY.get(district)
    if window is None:
        return False
    start, end = window
    return start <= day < end


def test_no_unexplained_seat_gaps(dim_rows) -> None:
    """
    Every VA Senate seat and House district 1-11 is covered from congress start
    through today, except the documented VA-11 vacancy after Connolly's death
    and before Walkinshaw was seated.
    """
    today = date.today()
    assert today >= CONGRESS_119_START

    day = CONGRESS_119_START
    while day <= today:
        for senator_slot in range(2):
            # Coverage is by existence of any two distinct senator windows;
            # check each bioguide isn't required day-by-day — check count.
            _ = senator_slot
        covered_sens = {
            r.bioguide_id
            for r in dim_rows
            if r.chamber == "Senate" and r.term_start <= day < r.term_end
        }
        assert len(covered_sens) == 2, f"Senate coverage gap on {day}: {covered_sens}"

        for district in range(1, 12):
            if _seat_covers_day(dim_rows, "House", district, day):
                continue
            if _day_in_allowed_vacancy(district, day):
                continue
            raise AssertionError(
                f"House VA-{district} has unexplained coverage gap on {day}"
            )
        day += timedelta(days=1)


def test_warehouse_query_shape(warehouse_conn) -> None:
    house_districts = warehouse_conn.execute(
        """
        SELECT COUNT(DISTINCT district_current)
        FROM dim_legislator
        WHERE chamber = 'House'
        """
    ).fetchone()[0]
    senators = warehouse_conn.execute(
        """
        SELECT COUNT(DISTINCT bioguide_id)
        FROM dim_legislator
        WHERE chamber = 'Senate'
        """
    ).fetchone()[0]
    assert house_districts == 11
    assert senators == 2


def test_map_district_columns_populated(dim_rows) -> None:
    for row in dim_rows:
        if row.chamber == "House":
            assert row.district_2025 == row.district_current
            assert row.district_2026 == row.district_current
        else:
            assert row.district_2025 is None
            assert row.district_2026 is None
