"""Warehouse and ingest contract checks (no persisted summary metrics)."""

from __future__ import annotations

import re
from collections import Counter
from datetime import date, timedelta
from typing import Mapping

import duckdb

from vact.constants import CONGRESS_119_END, CONGRESS_119_START
from vact.models.votes import VotePosition

VOTE_ID_RE = re.compile(r"^(h|s)-(\d+)-([12])-(\d+)$")


class MemberTotalsMismatchError(ValueError):
    """Raised when member vote counts disagree with source XML totals."""


def congress_start_year(congress: int) -> int:
    """1st Congress convened in 1789; each subsequent congress +2 years."""
    return 1789 + 2 * (congress - 1)


def session_date_bounds(congress: int, session: int) -> tuple[date, date]:
    """Inclusive start, exclusive end for a Congress session."""
    if session not in (1, 2):
        raise ValueError(f"session must be 1 or 2; got {session}")
    start_year = congress_start_year(congress)
    if session == 1:
        return date(start_year, 1, 3), date(start_year + 1, 1, 3)
    return date(start_year + 1, 1, 3), date(start_year + 2, 1, 3)


def is_congress_in_session(day: date | None = None) -> bool:
    """
    Coarse in-session heuristic for freshness gating.

    Treats August and late December as recess. Failure mode: a special session
    during recess would skip the freshness assert — prefer a manual `gaps` check
    when Congress returns early.
    """
    day = day or date.today()
    if not (CONGRESS_119_START <= day < CONGRESS_119_END):
        return False
    if day.weekday() >= 5:
        return False
    if day.month == 8:
        return False
    if day.month == 12 and day.day > 20:
        return False
    return True


def count_positions(positions: list[VotePosition] | list[str]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for pos in positions:
        key = pos.value if isinstance(pos, VotePosition) else str(pos)
        counter[key] += 1
    return {
        "YEA": int(counter.get("YEA", 0)),
        "NAY": int(counter.get("NAY", 0)),
        "PRESENT": int(counter.get("PRESENT", 0)),
        "NOT_VOTING": int(counter.get("NOT_VOTING", 0)),
    }


def assert_member_totals_match(
    *,
    vote_id: str,
    positions: list[VotePosition] | list[str],
    yea: int,
    nay: int,
    present: int,
    not_voting: int,
) -> None:
    """Fail ingest when parsed member rows disagree with source XML totals."""
    if not positions:
        raise MemberTotalsMismatchError(f"{vote_id}: no member votes parsed")
    got = count_positions(positions)
    expected = {
        "YEA": yea,
        "NAY": nay,
        "PRESENT": present,
        "NOT_VOTING": not_voting,
    }
    if got != expected:
        raise MemberTotalsMismatchError(
            f"{vote_id}: member position counts {got} != source totals {expected}"
        )


def assert_vote_id_canonical(vote_id: str) -> None:
    if not VOTE_ID_RE.match(vote_id):
        raise ValueError(f"vote_id does not match canonical regex: {vote_id!r}")


def assert_source_contracts(conn: duckdb.DuckDBPyConnection) -> None:
    """
    Source contracts over the warehouse.

    Bioguide resolution is scoped to Virginia `dim_legislator` (Prompt 1).
    Non-VA members appear in fact_member_vote without a dim_legislator row by
    design; the kit's literal national wording would reject every roll call.
    """
    orphan_votes = conn.execute(
        """
        SELECT v.vote_id
        FROM fact_vote v
        WHERE NOT EXISTS (
            SELECT 1 FROM fact_member_vote m WHERE m.vote_id = v.vote_id
        )
        """
    ).fetchall()
    if orphan_votes:
        raise AssertionError(f"fact_vote rows with no members: {orphan_votes[:10]}")

    mismatches = conn.execute(
        """
        WITH counts AS (
            SELECT
                vote_id,
                sum(CASE WHEN position = 'YEA' THEN 1 ELSE 0 END) AS yea_n,
                sum(CASE WHEN position = 'NAY' THEN 1 ELSE 0 END) AS nay_n,
                sum(CASE WHEN position = 'PRESENT' THEN 1 ELSE 0 END) AS present_n,
                sum(CASE WHEN position = 'NOT_VOTING' THEN 1 ELSE 0 END) AS nv_n
            FROM fact_member_vote
            GROUP BY 1
        )
        SELECT v.vote_id
        FROM fact_vote v
        JOIN counts c USING (vote_id)
        WHERE v.yea_total IS DISTINCT FROM c.yea_n
           OR v.nay_total IS DISTINCT FROM c.nay_n
           OR coalesce(v.present_total, -1) IS DISTINCT FROM c.present_n
           OR coalesce(v.not_voting_total, -1) IS DISTINCT FROM c.nv_n
        """
    ).fetchall()
    if mismatches:
        raise AssertionError(f"member totals mismatch for {mismatches[:10]}")

    # A real SCD2 gap is a member whose tracked service STARTS before this vote
    # but has no term row covering it — that is the mis-attribution this catches.
    # A vote predating the member's earliest tracked term is not a gap: it is an
    # era dim_legislator was never built for. The dimension holds the current VA
    # delegation, so historical backfills (111th/116th/117th) sit outside it, and
    # a sitting member's own earlier service would otherwise trip this.
    bad_va = conn.execute(
        """
        SELECT m.vote_id, m.bioguide_id, v.vote_date
        FROM fact_member_vote m
        JOIN fact_vote v USING (vote_id)
        WHERE EXISTS (
            SELECT 1 FROM dim_legislator d
            WHERE d.bioguide_id = m.bioguide_id
              AND d.term_start <= v.vote_date
        )
          AND NOT EXISTS (
            SELECT 1 FROM dim_legislator d
            WHERE d.bioguide_id = m.bioguide_id
              AND d.term_start <= v.vote_date
              AND v.vote_date < d.term_end
          )
        """
    ).fetchall()
    if bad_va:
        raise AssertionError(
            f"VA bioguide not valid on vote_date (SCD2 gap): {bad_va[:10]}"
        )

    date_rows = conn.execute(
        "SELECT vote_id, congress, session, vote_date FROM fact_vote"
    ).fetchall()
    for vote_id, congress, session, vote_date in date_rows:
        start, end = session_date_bounds(int(congress), int(session))
        if not (start <= vote_date < end):
            raise AssertionError(
                f"{vote_id}: vote_date {vote_date} outside session "
                f"{congress}/{session} bounds [{start}, {end})"
            )

    ids = [r[0] for r in conn.execute("SELECT vote_id FROM fact_vote").fetchall()]
    if len(ids) != len(set(ids)):
        raise AssertionError("fact_vote.vote_id is not unique")
    for vote_id in ids:
        assert_vote_id_canonical(vote_id)


def assert_referential_contracts(conn: duckdb.DuckDBPyConnection) -> None:
    orphans = conn.execute(
        """
        SELECT v.vote_id, v.bill_id
        FROM fact_vote v
        WHERE v.bill_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM dim_bill b WHERE b.bill_id = v.bill_id)
        """
    ).fetchall()
    if orphans:
        raise AssertionError(f"fact_vote.bill_id missing from dim_bill: {orphans[:10]}")

    bad_impact = conn.execute(
        """
        SELECT i.vote_id, v.vote_category
        FROM bridge_vote_impact i
        JOIN fact_vote v USING (vote_id)
        WHERE v.vote_category IN ('NOMINATION', 'CLOTURE')
        """
    ).fetchall()
    if bad_impact:
        raise AssertionError(
            f"bridge_vote_impact includes NOMINATION/CLOTURE: {bad_impact[:10]}"
        )


def assert_freshness_contract(
    conn: duckdb.DuckDBPyConnection,
    *,
    as_of: date | None = None,
    max_lag_days: int = 7,
) -> None:
    """When Congress looks in session, warehouse max(vote_date) must be fresh."""
    as_of = as_of or date.today()
    if not is_congress_in_session(as_of):
        return
    row = conn.execute("SELECT max(vote_date) FROM fact_vote").fetchone()
    if row is None or row[0] is None:
        raise AssertionError("fact_vote is empty while Congress is in session")
    max_date: date = row[0]
    if as_of - max_date > timedelta(days=max_lag_days):
        raise AssertionError(
            f"stale warehouse: max(vote_date)={max_date} as_of={as_of} "
            f"(>{max_lag_days} days)"
        )


def assert_all_warehouse_contracts(
    conn: duckdb.DuckDBPyConnection,
    *,
    as_of: date | None = None,
) -> None:
    assert_source_contracts(conn)
    assert_referential_contracts(conn)
    assert_freshness_contract(conn, as_of=as_of)
