"""Typer CLI entrypoint."""

from __future__ import annotations

from pathlib import Path

import typer

from vact.sources import house_rollcalls as house_source
from vact.sources import legislators as legislator_source
from vact.sources import senate_rollcalls as senate_source
from vact.transforms.legislators import build_dim_legislator_rows
from vact.transforms.lis_crosswalk import build_lis_bioguide_crosswalk
from vact.warehouse.load import upsert_dim_legislator

app = typer.Typer(
    name="vact",
    help="VA Congressional Tracker — ingest, classify, and report.",
    no_args_is_help=True,
)


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


if __name__ == "__main__":
    app()
