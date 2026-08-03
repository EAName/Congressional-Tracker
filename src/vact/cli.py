"""Typer CLI entrypoint."""

from __future__ import annotations

from pathlib import Path

import typer

from vact.sources import legislators as legislator_source
from vact.transforms.legislators import build_dim_legislator_rows
from vact.warehouse.load import upsert_dim_legislator

app = typer.Typer(
    name="vact",
    help="VA Congressional Tracker — ingest, classify, and report.",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """Root callback; subcommands registered by subsequent prompts."""


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
    # Parse offices for contract completeness; unused by dim_legislator itself.
    legislator_source.parse_district_offices(paths["legislators-district-offices"])
    rows = build_dim_legislator_rows(records)
    count = upsert_dim_legislator(rows, warehouse_path=warehouse)
    typer.echo(f"Upserted {count} dim_legislator rows (VA / 119th Congress).")


if __name__ == "__main__":
    app()
