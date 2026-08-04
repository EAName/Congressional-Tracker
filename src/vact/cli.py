"""Typer CLI entrypoint."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from vact.pipeline.backfill import backfill, incremental, write_coverage_report
from vact.sources import house_rollcalls as house_source
from vact.sources import legislators as legislator_source
from vact.sources import senate_rollcalls as senate_source
from vact.transforms import classify as classify_mod
from vact.transforms.legislators import build_dim_legislator_rows
from vact.transforms.lis_crosswalk import build_lis_bioguide_crosswalk
from vact.warehouse.load import load_house_vote, load_senate_vote, upsert_dim_legislator

app = typer.Typer(
    name="vact",
    help="VA Congressional Tracker — ingest, classify, and report.",
    no_args_is_help=True,
)
summaries_app = typer.Typer(help="Plain-language bill summary workflow.")
app.add_typer(summaries_app, name="summaries")


@app.callback()
def main() -> None:
    """Root callback; subcommands registered by subsequent prompts."""


def _lis_crosswalk(*, force: bool = False) -> dict[str, str]:
    paths = legislator_source.fetch_all(force=force)
    records = legislator_source.parse_legislators(
        paths["legislators-current"]
    ) + legislator_source.parse_legislators(paths["legislators-historical"])
    return build_lis_bioguide_crosswalk(records)


@app.command("ingest-legislators")
def ingest_legislators(
    force: bool = typer.Option(
        False,
        "--force",
        help="Re-download raw YAML even if a cache file already exists.",
    ),
    warehouse: Path | None = typer.Option(
        None,
        "--warehouse",
        help="Override path to warehouse.duckdb.",
        exists=False,
        dir_okay=False,
        writable=True,
        resolve_path=True,
    ),
) -> None:
    """Fetch congress-legislators YAML and upsert Virginia dim_legislator rows."""
    paths = legislator_source.fetch_all(force=force)
    records = legislator_source.parse_legislators(
        paths["legislators-current"]
    ) + legislator_source.parse_legislators(paths["legislators-historical"])
    legislator_source.parse_district_offices(paths["legislators-district-offices"])
    rows = build_dim_legislator_rows(records)
    count = upsert_dim_legislator(rows, warehouse_path=warehouse)
    typer.echo(f"Upserted {count} dim_legislator rows (VA / 119th Congress).")


@app.command("fetch-house-roll")
def fetch_house_roll(
    year: int = typer.Argument(..., help="Calendar year of the EVS file."),
    roll_number: int = typer.Argument(..., help="House roll call number."),
    force: bool = typer.Option(False, "--force", help="Re-download even if cached."),
) -> None:
    """Fetch one House Clerk roll-call XML into data/raw/house/."""
    path = house_source.fetch(year, roll_number, force=force)
    vote, members = house_source.parse(path)
    typer.echo(
        f"{path} — roll {vote.roll_number} on {vote.action_date} "
        f"({len(members)} member votes, result={vote.vote_result})"
    )


@app.command("fetch-senate-roll")
def fetch_senate_roll(
    session: int = typer.Argument(..., help="Session number (1 or 2)."),
    roll_number: int = typer.Argument(..., help="Senate vote number."),
    congress: int = typer.Option(119, "--congress", help="Congress number."),
    force: bool = typer.Option(False, "--force", help="Re-download even if cached."),
) -> None:
    """Fetch one Senate LIS roll-call XML and resolve lis_member_id → bioguide."""
    path = senate_source.fetch(congress, session, roll_number, force=force)
    vote, members = senate_source.parse(path, lis_to_bioguide=_lis_crosswalk())
    va = [m for m in members if m.state == "VA"]
    typer.echo(
        f"{path} — roll {vote.roll_number} on {vote.vote_date} "
        f"({len(members)} members, VA={len(va)}, result={vote.vote_result})"
    )


@app.command("load-house-roll")
def load_house_roll_cmd(
    year: int = typer.Argument(...),
    roll_number: int = typer.Argument(...),
    force: bool = typer.Option(False, "--force"),
    warehouse: Path | None = typer.Option(None, "--warehouse"),
) -> None:
    """Fetch (if needed) and MERGE-load one House roll call into the warehouse."""
    path = house_source.fetch(year, roll_number, force=force)
    vote, members = house_source.parse(path)
    vote_id = load_house_vote(vote, members, warehouse_path=warehouse)
    typer.echo(f"Loaded {vote_id} ({len(members)} member votes).")


@app.command("load-senate-roll")
def load_senate_roll_cmd(
    session: int = typer.Argument(...),
    roll_number: int = typer.Argument(...),
    congress: int = typer.Option(119, "--congress"),
    force: bool = typer.Option(False, "--force"),
    warehouse: Path | None = typer.Option(None, "--warehouse"),
) -> None:
    """Fetch (if needed) and MERGE-load one Senate roll call into the warehouse."""
    path = senate_source.fetch(congress, session, roll_number, force=force)
    vote, members = senate_source.parse(path, lis_to_bioguide=_lis_crosswalk())
    vote_id = load_senate_vote(vote, members, warehouse_path=warehouse)
    typer.echo(f"Loaded {vote_id} ({len(members)} member votes).")


@app.command("backfill")
def backfill_cmd(
    congress: int = typer.Option(119, "--congress"),
    chamber: str = typer.Option("both", "--chamber", help="house|senate|both"),
    start: str = typer.Option("2025-01-03", "--start", help="YYYY-MM-DD"),
    end: str = typer.Option("today", "--end", help="YYYY-MM-DD or 'today'"),
    force: bool = typer.Option(False, "--force", help="Re-download cached XML."),
    warehouse: Path | None = typer.Option(None, "--warehouse"),
) -> None:
    """Fetch and MERGE-load roll calls for a date window."""
    end_date = date.today() if end == "today" else date.fromisoformat(end)
    start_date = date.fromisoformat(start)
    counts = backfill(
        congress=congress,
        chamber=chamber,
        start=start_date,
        end=end_date,
        force=force,
        warehouse_path=warehouse,
    )
    typer.echo(
        f"Backfill complete: house={counts['house']} senate={counts['senate']} "
        f"({start_date} → {end_date})"
    )


@app.command("incremental")
def incremental_cmd(
    lookback_days: int = typer.Option(7, "--lookback-days"),
    congress: int = typer.Option(119, "--congress"),
    warehouse: Path | None = typer.Option(None, "--warehouse"),
) -> None:
    """Re-fetch lookback window (EVS is mutable) and pick up new rolls."""
    counts = incremental(
        lookback_days=lookback_days,
        congress=congress,
        warehouse_path=warehouse,
    )
    typer.echo(
        f"Incremental refresh: house={counts['house']} senate={counts['senate']} "
        f"(lookback_days={lookback_days})"
    )


@app.command("gaps")
def gaps_cmd(
    congress: int = typer.Option(119, "--congress"),
    warehouse: Path | None = typer.Option(None, "--warehouse"),
) -> None:
    """Report warehouse vs upstream gaps and write coverage.md heatmap."""
    path = write_coverage_report(congress=congress, warehouse_path=warehouse)
    typer.echo(f"Wrote {path}")


@app.command("classify")
def classify_cmd(
    new_only: bool = typer.Option(
        False,
        "--new-only",
        help="Only classify votes with no existing bridge_vote_impact rows.",
    ),
    no_llm: bool = typer.Option(
        False,
        "--no-llm",
        help="Skip Stage-2 LLM assist (rules only).",
    ),
    warehouse: Path | None = typer.Option(None, "--warehouse"),
) -> None:
    """Stage-1 rulebook (+ optional Stage-2 LLM) → bridge_vote_impact."""
    stats = classify_mod.classify_corpus(
        new_only=new_only,
        enable_llm=not no_llm,
        warehouse_path=warehouse,
    )
    typer.echo(
        "Classify complete: "
        f"scanned={stats['votes_scanned']} "
        f"excluded_personnel={stats['excluded_personnel']} "
        f"rule_tags={stats['rule_tags_written']} "
        f"llm_tags={stats['llm_tags_written']} "
        f"queued={stats['review_queue_rows']}"
    )


@app.command("promote")
def promote_cmd(
    queue: Path | None = typer.Option(
        None,
        "--queue",
        help="Path to adjudicated review_queue.csv",
        exists=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
    ),
    warehouse: Path | None = typer.Option(None, "--warehouse"),
) -> None:
    """Promote human-adjudicated review_queue rows as classified_by=HUMAN."""
    n = classify_mod.promote_review_queue(queue_path=queue, warehouse_path=warehouse)
    typer.echo(f"Promoted {n} HUMAN impact tag rows.")


@summaries_app.command("pending")
def summaries_pending_cmd(
    warehouse: Path | None = typer.Option(None, "--warehouse"),
) -> None:
    """List tagged votes whose bills lack a human plain_language_summary."""
    rows = classify_mod.list_summaries_pending(warehouse_path=warehouse)
    if not rows:
        typer.echo("No tagged bills missing plain_language_summary.")
        return
    typer.echo(f"{len(rows)} tagged bill-votes need plain_language_summary (<25 words, human):")
    for row in rows:
        tags = ",".join(row["tags"] or [])
        title = (row["title"] or "")[:80]
        typer.echo(
            f"{row['vote_date']}  {row['vote_id']}  {row['bill_id']}  [{tags}]  {title}"
        )


@app.command("reclassify")
def reclassify_cmd(
    all_: bool = typer.Option(
        False,
        "--all",
        help="Re-run the full rulebook over fact_vote.",
    ),
    confirm: bool = typer.Option(
        False,
        "--confirm",
        help="Required. Refuses without this flag.",
    ),
    warehouse: Path | None = typer.Option(None, "--warehouse"),
) -> None:
    """Full rulebook reclassify. Writes reclassify_diff.md before applying."""
    if not all_:
        raise typer.BadParameter("pass --all (partial reclassify is not supported)")
    if not confirm:
        raise typer.BadParameter("refusing without --confirm")
    path = classify_mod.reclassify_all(confirm=True, warehouse_path=warehouse)
    typer.echo(f"Reclassify complete. Diff: {path}")


if __name__ == "__main__":
    app()
