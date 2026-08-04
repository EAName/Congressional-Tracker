"""Backfill, incremental refresh, and coverage-gap reporting."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import duckdb
import structlog

from vact.paths import DATA_DIR
from vact.sources import house_rollcalls as house
from vact.sources import legislators as legislator_source
from vact.sources import senate_rollcalls as senate
from vact.transforms.lis_crosswalk import build_lis_bioguide_crosswalk
from vact.warehouse.connection import connect, ensure_schema
from vact.warehouse.load import load_house_vote, load_senate_vote
from vact.warehouse.meta import warehouse_content_fingerprint

logger = structlog.get_logger(__name__)

REPORTS_DIR = DATA_DIR / "reports"


@dataclass(frozen=True)
class GapRun:
    chamber: str
    year_or_session: str
    start: int
    end: int

    def label(self) -> str:
        if self.start == self.end:
            return f"{self.start}"
        return f"{self.start}-{self.end}"


def contiguous_runs(numbers: Iterable[int]) -> list[tuple[int, int]]:
    ordered = sorted(set(numbers))
    if not ordered:
        return []
    runs: list[tuple[int, int]] = []
    start = prev = ordered[0]
    for n in ordered[1:]:
        if n == prev + 1:
            prev = n
            continue
        runs.append((start, prev))
        start = prev = n
    runs.append((start, prev))
    return runs


def _years_in_range(start: date, end: date) -> list[int]:
    return list(range(start.year, end.year + 1))


def _lis_crosswalk() -> dict[str, str]:
    paths = legislator_source.fetch_all()
    records = legislator_source.parse_legislators(
        paths["legislators-current"]
    ) + legislator_source.parse_legislators(paths["legislators-historical"])
    return build_lis_bioguide_crosswalk(records)


def ingest_house_year(
    year: int,
    *,
    start: date,
    end: date,
    force: bool,
    conn: duckdb.DuckDBPyConnection,
) -> int:
    rolls = house.discover(year, force=force)
    loaded = 0
    skipped = 0
    for roll_number in sorted(rolls):
        path = house.fetch(year, roll_number, force=force)
        try:
            vote, members = house.parse(path)
        except house.HouseRollUnsupported as err:
            skipped += 1
            logger.warning(
                "house_roll_skipped",
                year=year,
                roll_number=roll_number,
                reason=str(err),
            )
            continue
        if vote.action_date < start or vote.action_date > end:
            continue
        load_house_vote(vote, members, conn=conn)
        loaded += 1
        if loaded % 25 == 0:
            logger.info(
                "house_backfill_progress",
                year=year,
                loaded=loaded,
                skipped=skipped,
                of=len(rolls),
            )
    logger.info(
        "house_year_complete", year=year, loaded=loaded, skipped=skipped, discovered=len(rolls)
    )
    return loaded


def ingest_senate_session(
    congress: int,
    session: int,
    *,
    start: date,
    end: date,
    force: bool,
    conn: duckdb.DuckDBPyConnection,
    lis_to_bioguide: dict[str, str],
) -> int:
    rolls = senate.discover(congress, session, force=force)
    loaded = 0
    for roll_number in sorted(rolls):
        path = senate.fetch(congress, session, roll_number, force=force)
        vote, members = senate.parse(path, lis_to_bioguide=lis_to_bioguide)
        if vote.vote_date < start or vote.vote_date > end:
            continue
        load_senate_vote(vote, members, conn=conn)
        loaded += 1
        if loaded % 25 == 0:
            logger.info(
                "senate_backfill_progress",
                congress=congress,
                session=session,
                loaded=loaded,
                of=len(rolls),
            )
    return loaded


def backfill(
    *,
    congress: int = 119,
    chamber: str = "both",
    start: date,
    end: date,
    force: bool = False,
    warehouse_path: Path | None = None,
) -> dict[str, int]:
    """Fetch and MERGE-load roll calls in [start, end] for the requested chambers."""
    if chamber not in {"house", "senate", "both"}:
        raise ValueError("chamber must be house, senate, or both")
    if end < start:
        raise ValueError("end must be on or after start")

    conn = connect(warehouse_path)
    try:
        ensure_schema(conn)
        counts = {"house": 0, "senate": 0}
        if chamber in {"house", "both"}:
            for year in _years_in_range(start, end):
                counts["house"] += ingest_house_year(
                    year, start=start, end=end, force=force, conn=conn
                )
        if chamber in {"senate", "both"}:
            xw = _lis_crosswalk()
            for session in (1, 2):
                counts["senate"] += ingest_senate_session(
                    congress,
                    session,
                    start=start,
                    end=end,
                    force=force,
                    conn=conn,
                    lis_to_bioguide=xw,
                )
        return counts
    finally:
        conn.close()


def _warehouse_votes_in_window(
    conn: duckdb.DuckDBPyConnection, window_start: date
) -> list[tuple[str, int, int, int, date]]:
    return conn.execute(
        """
        SELECT chamber, congress, session, roll_number, vote_date
        FROM fact_vote
        WHERE vote_date >= ?
        ORDER BY chamber, congress, session, roll_number
        """,
        [window_start],
    ).fetchall()


def _vote_ids(conn: duckdb.DuckDBPyConnection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT vote_id FROM fact_vote").fetchall()}


def incremental(
    *,
    lookback_days: int = 7,
    congress: int = 119,
    warehouse_path: Path | None = None,
    as_of: date | None = None,
) -> dict[str, object]:
    """
    Re-fetch and upsert every roll call with vote_date in the lookback window,
    then discover/load any newer rolls not yet in the warehouse.

    Returns house/senate load counts plus `changed`, `new_vote_ids`, and
    before/after fingerprints for silent no-op detection in CI.
    """
    if lookback_days < 0:
        raise ValueError("lookback_days must be >= 0")
    today = as_of or date.today()
    window_start = today - timedelta(days=lookback_days)

    conn = connect(warehouse_path)
    try:
        ensure_schema(conn)
        before_fp = warehouse_content_fingerprint(conn)
        before_ids = _vote_ids(conn)
        refreshed = {"house": 0, "senate": 0}
        xw: dict[str, str] | None = None

        for chamber, cng, session, roll_number, vote_date in _warehouse_votes_in_window(
            conn, window_start
        ):
            if chamber == "House":
                path = house.fetch(vote_date.year, roll_number, force=True)
                vote, members = house.parse(path)
                load_house_vote(vote, members, conn=conn)
                refreshed["house"] += 1
            else:
                if xw is None:
                    xw = _lis_crosswalk()
                path = senate.fetch(cng, session, roll_number, force=True)
                vote, members = senate.parse(path, lis_to_bioguide=xw)
                load_senate_vote(vote, members, conn=conn)
                refreshed["senate"] += 1

        # Pull anything newer than current warehouse maxes.
        for year in _years_in_range(window_start, today):
            upstream = house.discover(year, force=False)
            known = {
                r[0]
                for r in conn.execute(
                    """
                    SELECT roll_number FROM fact_vote
                    WHERE chamber = 'House' AND EXTRACT(year FROM vote_date) = ?
                    """,
                    [year],
                ).fetchall()
            }
            for roll_number in sorted(upstream - known):
                path = house.fetch(year, roll_number, force=True)
                vote, members = house.parse(path)
                if vote.action_date < window_start:
                    continue
                load_house_vote(vote, members, conn=conn)
                refreshed["house"] += 1

        if xw is None:
            xw = _lis_crosswalk()
        for session in (1, 2):
            upstream = senate.discover(congress, session, force=False)
            known = {
                r[0]
                for r in conn.execute(
                    """
                    SELECT roll_number FROM fact_vote
                    WHERE chamber = 'Senate' AND congress = ? AND session = ?
                    """,
                    [congress, session],
                ).fetchall()
            }
            for roll_number in sorted(upstream - known):
                path = senate.fetch(congress, session, roll_number, force=True)
                vote, members = senate.parse(path, lis_to_bioguide=xw)
                if vote.vote_date < window_start:
                    continue
                load_senate_vote(vote, members, conn=conn)
                refreshed["senate"] += 1

        after_ids = _vote_ids(conn)
        after_fp = warehouse_content_fingerprint(conn)
        new_vote_ids = sorted(after_ids - before_ids)
        return {
            "house": refreshed["house"],
            "senate": refreshed["senate"],
            "changed": before_fp != after_fp or bool(new_vote_ids),
            "new_vote_ids": new_vote_ids,
            "fingerprint_before": before_fp,
            "fingerprint_after": after_fp,
        }
    finally:
        conn.close()


def _max_warehouse_house_by_year(conn: duckdb.DuckDBPyConnection) -> dict[int, int]:
    rows = conn.execute(
        """
        SELECT EXTRACT(year FROM vote_date)::INTEGER AS y, MAX(roll_number)
        FROM fact_vote
        WHERE chamber = 'House'
        GROUP BY 1
        """
    ).fetchall()
    return {int(y): int(mx) for y, mx in rows}


def _max_warehouse_senate(
    conn: duckdb.DuckDBPyConnection, congress: int
) -> dict[int, int]:
    rows = conn.execute(
        """
        SELECT session, MAX(roll_number)
        FROM fact_vote
        WHERE chamber = 'Senate' AND congress = ?
        GROUP BY 1
        """,
        [congress],
    ).fetchall()
    return {int(session): int(mx) for session, mx in rows}


def compute_gaps(
    *,
    congress: int = 119,
    warehouse_path: Path | None = None,
) -> dict[str, object]:
    """
    Compare warehouse coverage to upstream discovery.

    Distinguishes missing-in-warehouse (upstream has it) from absent-upstream.
    """
    conn = connect(warehouse_path)
    try:
        ensure_schema(conn)
        house_wh = _max_warehouse_house_by_year(conn)
        senate_wh = _max_warehouse_senate(conn, congress)

        house_gaps: list[GapRun] = []
        house_upstream: dict[int, set[int]] = {}
        for year in sorted(set(house_wh) | {date.today().year, date.today().year - 1}):
            upstream = house.discover(year, force=False)
            house_upstream[year] = upstream
            known = {
                r[0]
                for r in conn.execute(
                    """
                    SELECT roll_number FROM fact_vote
                    WHERE chamber = 'House' AND EXTRACT(year FROM vote_date) = ?
                    """,
                    [year],
                ).fetchall()
            }
            missing = upstream - known
            for start, end in contiguous_runs(missing):
                house_gaps.append(
                    GapRun("House", str(year), start, end)
                )

        senate_gaps: list[GapRun] = []
        senate_upstream: dict[int, set[int]] = {}
        for session in (1, 2):
            upstream = senate.discover(congress, session, force=False)
            senate_upstream[session] = upstream
            known = {
                r[0]
                for r in conn.execute(
                    """
                    SELECT roll_number FROM fact_vote
                    WHERE chamber = 'Senate' AND congress = ? AND session = ?
                    """,
                    [congress, session],
                ).fetchall()
            }
            missing = upstream - known
            for start, end in contiguous_runs(missing):
                senate_gaps.append(
                    GapRun("Senate", f"{congress}-{session}", start, end)
                )

        return {
            "house_warehouse_max": house_wh,
            "senate_warehouse_max": senate_wh,
            "house_upstream_max": {y: max(s) if s else 0 for y, s in house_upstream.items()},
            "senate_upstream_max": {
                s: max(nums) if nums else 0 for s, nums in senate_upstream.items()
            },
            "house_gaps": house_gaps,
            "senate_gaps": senate_gaps,
            "house_upstream_counts": {y: len(s) for y, s in house_upstream.items()},
            "senate_upstream_counts": {s: len(nums) for s, nums in senate_upstream.items()},
        }
    finally:
        conn.close()


def write_coverage_report(
    *,
    congress: int = 119,
    warehouse_path: Path | None = None,
    output_path: Path | None = None,
) -> Path:
    """Emit weekly vote-count heatmap plus gap runs to data/reports/coverage.md."""
    gap_info = compute_gaps(congress=congress, warehouse_path=warehouse_path)
    conn = connect(warehouse_path)
    try:
        ensure_schema(conn)
        weekly = conn.execute(
            """
            SELECT
                chamber,
                date_trunc('week', vote_date)::DATE AS week_start,
                COUNT(*) AS votes
            FROM fact_vote
            GROUP BY 1, 2
            ORDER BY 2, 1
            """
        ).fetchall()
        totals = conn.execute(
            """
            SELECT chamber, COUNT(*), MIN(vote_date), MAX(vote_date)
            FROM fact_vote
            GROUP BY 1
            ORDER BY 1
            """
        ).fetchall()
    finally:
        conn.close()

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = output_path or (REPORTS_DIR / "coverage.md")
    lines = [
        "# Coverage report",
        "",
        f"Generated for congress {congress}.",
        "",
        "## Warehouse totals (live query)",
        "",
        "| Chamber | Votes | Min date | Max date |",
        "|---|---:|---|---|",
    ]
    for chamber, n, mn, mx in totals:
        lines.append(f"| {chamber} | {n} | {mn} | {mx} |")
    if not totals:
        lines.append("| _(empty)_ | 0 | — | — |")

    lines += [
        "",
        "## Upstream vs warehouse max roll",
        "",
        f"- House warehouse max by year: `{gap_info['house_warehouse_max']}`",
        f"- House upstream max by year: `{gap_info['house_upstream_max']}`",
        f"- Senate warehouse max by session: `{gap_info['senate_warehouse_max']}`",
        f"- Senate upstream max by session: `{gap_info['senate_upstream_max']}`",
        "",
        "## Missing in warehouse (present upstream)",
        "",
    ]
    house_gaps: list[GapRun] = gap_info["house_gaps"]  # type: ignore[assignment]
    senate_gaps: list[GapRun] = gap_info["senate_gaps"]  # type: ignore[assignment]
    if not house_gaps and not senate_gaps:
        lines.append("No gaps detected relative to upstream discovery.")
    else:
        lines.append("| Chamber | Scope | Missing rolls |")
        lines.append("|---|---|---|")
        for g in house_gaps + senate_gaps:
            lines.append(f"| {g.chamber} | {g.year_or_session} | {g.label()} |")

    lines += ["", "## Weekly heatmap (warehouse votes)", "", "| Week starting | House | Senate |", "|---|---:|---:|"]
    by_week: dict[date, dict[str, int]] = {}
    for chamber, week_start, votes in weekly:
        by_week.setdefault(week_start, {"House": 0, "Senate": 0})
        by_week[week_start][chamber] = votes
    for week_start in sorted(by_week):
        row = by_week[week_start]
        lines.append(
            f"| {week_start} | {row.get('House', 0)} | {row.get('Senate', 0)} |"
        )
    if not by_week:
        lines.append("| _(no votes)_ | 0 | 0 |")

    lines += [
        "",
        "## Interpretation",
        "",
        "- Empty weeks in the warehouse heatmap are **not** proof that Congress took no votes.",
        "- Use the upstream max / missing-roll table to separate warehouse holes from true recesses.",
        "",
    ]
    out.write_text("\n".join(lines), encoding="utf-8")
    return out
