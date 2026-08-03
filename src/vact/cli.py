"""Typer CLI entrypoint. Commands arrive in later prompts."""

from __future__ import annotations

import typer

app = typer.Typer(
    name="vact",
    help="VA Congressional Tracker — ingest, classify, and report.",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """Root callback; subcommands registered by subsequent prompts."""


if __name__ == "__main__":
    app()
