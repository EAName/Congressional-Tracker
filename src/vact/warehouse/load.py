"""MERGE-style loads into the DuckDB warehouse."""

from __future__ import annotations

from pathlib import Path

import duckdb

from vact.models.house_rollcalls import HouseMemberVoteRecord, HouseVoteRecord
from vact.models.legislators import DimDistrictRow, DimLegislatorRow
from vact.models.senate_rollcalls import SenateMemberVoteRecord, SenateVoteRecord
from vact.models.votes import VotePosition
from vact.transforms.ids import (
    BillRef,
    canonical_vote_id,
    infer_passed,
    normalize_vote_type,
    parse_bill_ref,
)
from vact.transforms.vote_category import classify_vote_category
from vact.warehouse.connection import connect, ensure_schema

_UPSERT_LEGISLATOR = """
INSERT INTO dim_legislator AS t (
    bioguide_id, govtrack_id, icpsr_id, lis_member_id, full_name, chamber, state,
    district_current, district_2025, district_2026, party,
    term_start, term_end, first_elected, is_incumbent, website
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (bioguide_id, term_start) DO UPDATE SET
    govtrack_id = excluded.govtrack_id,
    icpsr_id = excluded.icpsr_id,
    lis_member_id = excluded.lis_member_id,
    full_name = excluded.full_name,
    chamber = excluded.chamber,
    state = excluded.state,
    district_current = excluded.district_current,
    district_2025 = excluded.district_2025,
    district_2026 = excluded.district_2026,
    party = excluded.party,
    term_end = excluded.term_end,
    first_elected = excluded.first_elected,
    is_incumbent = excluded.is_incumbent,
    website = excluded.website
"""

_UPSERT_DISTRICT = """
INSERT INTO dim_district AS t (
    district_number, map_version, incumbent_bioguide, partisan_lean, is_target
) VALUES (?, ?, ?, ?, ?)
ON CONFLICT (district_number, map_version) DO UPDATE SET
    incumbent_bioguide = excluded.incumbent_bioguide,
    partisan_lean = excluded.partisan_lean,
    is_target = excluded.is_target
"""

_UPSERT_BILL = """
INSERT INTO dim_bill AS t (
    bill_id, congress, bill_type, bill_number, bill_number_raw,
    title, short_title, plain_language_summary, sponsor_bioguide, introduced_date, policy_area
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (bill_id) DO UPDATE SET
    congress = excluded.congress,
    bill_type = excluded.bill_type,
    bill_number = coalesce(excluded.bill_number, t.bill_number),
    bill_number_raw = coalesce(excluded.bill_number_raw, t.bill_number_raw),
    title = coalesce(excluded.title, t.title),
    short_title = coalesce(excluded.short_title, t.short_title),
    plain_language_summary = coalesce(t.plain_language_summary, excluded.plain_language_summary),
    sponsor_bioguide = coalesce(excluded.sponsor_bioguide, t.sponsor_bioguide),
    introduced_date = coalesce(excluded.introduced_date, t.introduced_date),
    policy_area = coalesce(excluded.policy_area, t.policy_area)
"""

_UPSERT_VOTE = """
INSERT INTO fact_vote AS t (
    vote_id, congress, session, chamber, roll_number, vote_date,
    vote_question, vote_type, vote_category, result, passed, bill_id,
    yea_total, nay_total, source_url
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (vote_id) DO UPDATE SET
    congress = excluded.congress,
    session = excluded.session,
    chamber = excluded.chamber,
    roll_number = excluded.roll_number,
    vote_date = excluded.vote_date,
    vote_question = excluded.vote_question,
    vote_type = excluded.vote_type,
    vote_category = excluded.vote_category,
    result = excluded.result,
    passed = excluded.passed,
    bill_id = excluded.bill_id,
    yea_total = excluded.yea_total,
    nay_total = excluded.nay_total,
    source_url = excluded.source_url
"""

_UPSERT_MEMBER_VOTE = """
INSERT INTO fact_member_vote AS t (vote_id, bioguide_id, position)
VALUES (?, ?, ?)
ON CONFLICT (vote_id, bioguide_id) DO UPDATE SET
    position = excluded.position
"""


def ensure_dim_legislator(conn: duckdb.DuckDBPyConnection) -> None:
    ensure_schema(conn)


def upsert_dim_legislator(
    rows: list[DimLegislatorRow],
    *,
    conn: duckdb.DuckDBPyConnection | None = None,
    warehouse_path: Path | None = None,
) -> int:
    owns_conn = conn is None
    db = conn or connect(warehouse_path)
    try:
        ensure_schema(db)
        if not rows:
            return 0
        payload = [
            (
                row.bioguide_id,
                row.govtrack_id,
                row.icpsr_id,
                row.lis_member_id,
                row.full_name,
                row.chamber,
                row.state,
                row.district_current,
                row.district_2025,
                row.district_2026,
                row.party,
                row.term_start,
                row.term_end,
                row.first_elected,
                row.is_incumbent,
                row.website,
            )
            for row in rows
        ]
        db.executemany(_UPSERT_LEGISLATOR, payload)
        return len(rows)
    finally:
        if owns_conn:
            db.close()


def upsert_dim_district(
    rows: list[DimDistrictRow],
    *,
    conn: duckdb.DuckDBPyConnection | None = None,
    warehouse_path: Path | None = None,
) -> int:
    owns_conn = conn is None
    db = conn or connect(warehouse_path)
    try:
        ensure_schema(db)
        if not rows:
            return 0
        payload = [
            (
                row.district_number,
                row.map_version,
                row.incumbent_bioguide,
                row.partisan_lean,
                row.is_target,
            )
            for row in rows
        ]
        db.executemany(_UPSERT_DISTRICT, payload)
        return len(rows)
    finally:
        if owns_conn:
            db.close()


def upsert_dim_bill(
    bill: BillRef,
    *,
    title: str | None = None,
    short_title: str | None = None,
    conn: duckdb.DuckDBPyConnection,
) -> None:
    conn.execute(
        _UPSERT_BILL,
        [
            bill.bill_id,
            bill.congress,
            bill.bill_type,
            bill.bill_number,
            bill.bill_number_raw,
            title,
            short_title,
            None,  # plain_language_summary: human-authored later
            None,
            None,
            None,
        ],
    )


def upsert_member_votes(
    vote_id: str,
    members: list[tuple[str, VotePosition]],
    *,
    conn: duckdb.DuckDBPyConnection,
) -> int:
    payload = [(vote_id, bioguide_id, position.value) for bioguide_id, position in members]
    if not payload:
        return 0
    conn.executemany(_UPSERT_MEMBER_VOTE, payload)
    return len(payload)


def load_house_vote(
    vote: HouseVoteRecord,
    members: list[HouseMemberVoteRecord],
    *,
    conn: duckdb.DuckDBPyConnection | None = None,
    warehouse_path: Path | None = None,
) -> str:
    """Upsert one House roll call and its member positions. Returns vote_id."""
    owns = conn is None
    db = conn or connect(warehouse_path)
    try:
        ensure_schema(db)
        vote_id = canonical_vote_id("House", vote.congress, vote.session, vote.roll_number)
        question = vote.vote_question or ""
        category = classify_vote_category(question, vote.vote_type, conn=db)
        bill = parse_bill_ref(vote.legis_num, vote.congress)
        if bill is not None:
            upsert_dim_bill(bill, title=vote.vote_desc, conn=db)

        db.execute(
            _UPSERT_VOTE,
            [
                vote_id,
                vote.congress,
                vote.session,
                "House",
                vote.roll_number,
                vote.action_date,
                vote.vote_question,
                normalize_vote_type(vote.vote_type),
                category,
                vote.vote_result,
                infer_passed(vote.vote_result),
                bill.bill_id if bill else None,
                vote.totals.yea,
                vote.totals.nay,
                vote.source_url,
            ],
        )
        upsert_member_votes(
            vote_id,
            [(m.bioguide_id, m.position) for m in members],
            conn=db,
        )
        return vote_id
    finally:
        if owns:
            db.close()


def load_senate_vote(
    vote: SenateVoteRecord,
    members: list[SenateMemberVoteRecord],
    *,
    conn: duckdb.DuckDBPyConnection | None = None,
    warehouse_path: Path | None = None,
) -> str:
    """Upsert one Senate roll call and its member positions. Returns vote_id."""
    owns = conn is None
    db = conn or connect(warehouse_path)
    try:
        ensure_schema(db)
        vote_id = canonical_vote_id("Senate", vote.congress, vote.session, vote.roll_number)
        question = vote.vote_question or vote.vote_question_text or ""
        category = classify_vote_category(question, None, conn=db)

        bill: BillRef | None = None
        title: str | None = vote.vote_title
        short_title: str | None = None
        if vote.document is not None:
            label = vote.document.name
            if not label and vote.document.document_type and vote.document.document_number:
                label = f"{vote.document.document_type}{vote.document.document_number}"
            bill = parse_bill_ref(label, vote.congress)
            title = vote.document.title or title
            short_title = vote.document.short_title
            if bill is not None:
                upsert_dim_bill(bill, title=title, short_title=short_title, conn=db)

        db.execute(
            _UPSERT_VOTE,
            [
                vote_id,
                vote.congress,
                vote.session,
                "Senate",
                vote.roll_number,
                vote.vote_date,
                question,
                None,
                category,
                vote.vote_result,
                infer_passed(vote.vote_result),
                bill.bill_id if bill else None,
                vote.totals.yea,
                vote.totals.nay,
                vote.source_url,
            ],
        )
        upsert_member_votes(
            vote_id,
            [(m.bioguide_id, m.position) for m in members],
            conn=db,
        )
        return vote_id
    finally:
        if owns:
            db.close()
