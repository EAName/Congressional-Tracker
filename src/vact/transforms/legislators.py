"""Build Virginia-scoped SCD2 dim_legislator rows for the 119th Congress."""

from __future__ import annotations

from datetime import date

from vact.constants import CONGRESS_119_END, CONGRESS_119_START
from vact.models.legislators import DimLegislatorRow, LegislatorRecord, LegislatorTerm


def _term_overlaps_119th(term: LegislatorTerm) -> bool:
    return (
        term.state == "VA"
        and term.start < CONGRESS_119_END
        and term.end > CONGRESS_119_START
    )


def _full_name(record: LegislatorRecord) -> str:
    if record.name.official_full:
        return record.name.official_full
    parts = [
        p
        for p in (record.name.first, record.name.middle, record.name.last)
        if p
    ]
    name = " ".join(parts)
    if record.name.suffix:
        name = f"{name}, {record.name.suffix}"
    if not name:
        raise ValueError(f"legislator {record.id.bioguide} has no usable name")
    return name


def _first_elected_year(record: LegislatorRecord) -> int:
    if not record.terms:
        raise ValueError(f"legislator {record.id.bioguide} has no terms")
    return min(term.start for term in record.terms).year


def _website_for_term(term: LegislatorTerm) -> str | None:
    return term.url


def dim_row_from_term(
    record: LegislatorRecord,
    term: LegislatorTerm,
    *,
    as_of: date | None = None,
) -> DimLegislatorRow:
    """Map one overlapping VA term into a warehouse row."""
    today = as_of or date.today()
    chamber = "Senate" if term.type == "sen" else "House"
    return DimLegislatorRow(
        bioguide_id=record.id.bioguide,
        govtrack_id=record.id.govtrack,
        icpsr_id=record.id.icpsr,
        lis_member_id=record.id.lis,
        full_name=_full_name(record),
        chamber=chamber,
        state="VA",
        district_current=None if term.type == "sen" else term.district,
        party=term.party,
        term_start=term.start,
        term_end=term.end,
        first_elected=_first_elected_year(record),
        is_incumbent=term.start <= today < term.end,
        website=_website_for_term(term),
    )


def build_dim_legislator_rows(
    records: list[LegislatorRecord],
    *,
    as_of: date | None = None,
) -> list[DimLegislatorRow]:
    """
    Filter congress-legislators records to VA terms overlapping the 119th Congress.

    Emits Type-2 rows keyed on (bioguide_id, term_start). Predecessor and
    successor for the same district both appear when their windows both
    overlap the 119th Congress.
    """
    rows: list[DimLegislatorRow] = []
    seen: set[tuple[str, date]] = set()

    for record in records:
        if not record.id.bioguide:
            raise ValueError("legislator missing bioguide_id")
        for term in record.terms:
            if not _term_overlaps_119th(term):
                continue
            key = (record.id.bioguide, term.start)
            if key in seen:
                continue
            seen.add(key)
            rows.append(dim_row_from_term(record, term, as_of=as_of))

    rows.sort(key=lambda r: (r.chamber, r.district_current or 0, r.term_start, r.bioguide_id))
    return rows
