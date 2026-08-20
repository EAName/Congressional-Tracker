"""Typer CLI entrypoint."""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

import typer

from vact.pipeline.backfill import backfill, incremental, write_coverage_report
from vact.sources import house_rollcalls as house_source
from vact.sources import legislators as legislator_source
from vact.sources import senate_rollcalls as senate_source
from vact.transforms import classify as classify_mod
from vact.transforms.districts import build_dim_district_rows
from vact.transforms.legislators import build_dim_legislator_rows
from vact.transforms.lis_crosswalk import build_lis_bioguide_crosswalk
from vact.warehouse.connection import connect, ensure_schema
from vact.warehouse.contracts import assert_all_warehouse_contracts
from vact.warehouse.load import (
    load_house_vote,
    load_senate_vote,
    upsert_dim_district,
    upsert_dim_legislator,
)

app = typer.Typer(
    name="vact",
    help="VA Congressional Tracker — ingest, classify, and report.",
    no_args_is_help=True,
)
summaries_app = typer.Typer(help="Plain-language bill summary workflow.")
app.add_typer(summaries_app, name="summaries")
sheets_app = typer.Typer(help="Google Sheets audit export.")
app.add_typer(sheets_app, name="sheets")
valence_app = typer.Typer(help="Vote valence adjudication (scoring-frame input).")
app.add_typer(valence_app, name="valence")
cosp_app = typer.Typer(help="Cosponsorship candidate ingest (separate from vote scores).")
app.add_typer(cosp_app, name="cosp")
votes_app = typer.Typer(help="Versioned votes.csv adjudication layer.")
app.add_typer(votes_app, name="votes")
races_app = typer.Typer(help="Midterm race registry and FEC snapshots.")
app.add_typer(races_app, name="races")
fec_app = typer.Typer(help="OpenFEC campaign-finance snapshots.")
app.add_typer(fec_app, name="fec")
seats_app = typer.Typer(help="Pre-registered House seat model.")
app.add_typer(seats_app, name="seats")


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
    district_count = upsert_dim_district(
        build_dim_district_rows(), warehouse_path=warehouse
    )
    typer.echo(
        f"Upserted {count} dim_legislator rows (VA / 119th Congress); "
        f"{district_count} dim_district rows (map_versions 2021+2026)."
    )


@app.command("ingest-districts")
def ingest_districts(
    warehouse: Path | None = typer.Option(None, "--warehouse"),
) -> None:
    """Upsert dim_district from config/districts.yaml (both map_versions)."""
    count = upsert_dim_district(build_dim_district_rows(), warehouse_path=warehouse)
    typer.echo(f"Upserted {count} dim_district rows (map_versions 2021+2026).")


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
    notify: bool = typer.Option(
        True,
        "--notify/--no-notify",
        help="Emit outreach signals for new party-line tagged votes.",
    ),
) -> None:
    """Re-fetch lookback window (EVS is mutable) and pick up new rolls."""
    from vact.pipeline.notify import find_party_line_splits, notify_outreach
    from vact.paths import WAREHOUSE_PATH

    counts = incremental(
        lookback_days=lookback_days,
        congress=congress,
        warehouse_path=warehouse,
    )
    changed = bool(counts.get("changed"))
    new_ids = list(counts.get("new_vote_ids") or [])
    typer.echo(
        f"Incremental refresh: house={counts['house']} senate={counts['senate']} "
        f"changed={changed} new_votes={len(new_ids)} "
        f"(lookback_days={lookback_days})"
    )
    if not changed:
        typer.echo("No content change — silent no-op (no notification).")
        return
    if notify and new_ids:
        conn = connect(warehouse or WAREHOUSE_PATH)
        try:
            ensure_schema(conn)
            signals = find_party_line_splits(conn, vote_ids=new_ids)
        finally:
            conn.close()
        if signals:
            notify_outreach(signals)
            typer.echo(f"Outreach signals: {len(signals)} party-line tagged votes.")


@app.command("dimensions")
def dimensions_cmd(
    force: bool = typer.Option(False, "--force", help="Rebuild even if upstream SHA matches."),
    warehouse: Path | None = typer.Option(None, "--warehouse"),
) -> None:
    """Refresh dim_legislator / dim_district when congress-legislators SHA changes."""
    from vact.pipeline.dimensions import refresh_dimensions
    from vact.pipeline.notify import notify_pipeline_failure

    result = refresh_dimensions(force=force, warehouse_path=warehouse)
    if result.skipped:
        typer.echo(f"Dimensions unchanged (sha={result.upstream_sha[:12]}).")
        raise typer.Exit(code=0)
    typer.echo(
        f"Dimensions refreshed: sha={result.upstream_sha[:12]} "
        f"legislators={result.legislator_rows} districts={result.district_rows} "
        f"delegation_changed={result.delegation_changed}"
    )
    if result.delegation_changed:
        # Seat change is news before it is a data issue — always surface.
        notify_pipeline_failure(
            "Virginia delegation dimension changed",
            details={
                "upstream_sha": result.upstream_sha,
                "previous_sha": result.previous_sha,
                "delegation_fp": result.delegation_fp,
            },
        )
        typer.echo("Alerted: Virginia delegation fingerprint changed.")


@app.command("gaps")
def gaps_cmd(
    congress: int = typer.Option(119, "--congress"),
    warehouse: Path | None = typer.Option(None, "--warehouse"),
) -> None:
    """Report warehouse vs upstream gaps and write coverage.md heatmap."""
    path = write_coverage_report(congress=congress, warehouse_path=warehouse)
    typer.echo(f"Wrote {path}")


@app.command("contracts")
def contracts_cmd(
    warehouse: Path | None = typer.Option(None, "--warehouse"),
) -> None:
    """Run source, referential, and freshness warehouse contracts."""
    from vact.paths import WAREHOUSE_PATH

    conn = connect(warehouse or WAREHOUSE_PATH)
    try:
        ensure_schema(conn)
        assert_all_warehouse_contracts(conn)
    finally:
        conn.close()
    typer.echo("All warehouse contracts passed.")


@app.command("ingest-bills")
def ingest_bills_cmd(
    api_key: str = typer.Option(
        None,
        "--api-key",
        envvar="CONGRESS_API_KEY",
        help="Congress.gov API key (or set CONGRESS_API_KEY).",
    ),
    force: bool = typer.Option(False, "--force", help="Re-fetch bills that already have a policy_area."),
    limit: int | None = typer.Option(None, "--limit", help="Cap the number of bills fetched."),
    warehouse: Path | None = typer.Option(None, "--warehouse"),
) -> None:
    """Enrich dim_bill with Congress.gov policy_area (classification signal)."""
    from vact.pipeline import bills as bills_pipeline

    if not api_key:
        raise typer.BadParameter("set CONGRESS_API_KEY (e.g. in .env) or pass --api-key")
    stats = bills_pipeline.ingest_bills(api_key=api_key, warehouse_path=warehouse, force=force, limit=limit)
    typer.echo(
        "Bill enrichment complete: "
        f"scanned={stats['scanned']} enriched={stats['enriched']} "
        f"with_policy_area={stats['with_policy_area']} "
        f"not_found={stats['not_found']} errors={stats['errors']}"
    )


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


@sheets_app.command("auth")
def sheets_auth_cmd() -> None:
    """Browser OAuth login (Desktop client). Saves token for later push/preflight."""
    from vact.exports import sheets as sheets_mod

    os.environ.setdefault("VACT_SHEETS_AUTH", "oauth")
    try:
        path = sheets_mod.run_oauth_login()
    except sheets_mod.SheetsConfigError as err:
        typer.echo(str(err), err=True)
        raise typer.Exit(code=2) from err
    typer.echo(f"OAuth token saved → {path}")
    typer.echo("Next: VACT_SHEETS_AUTH=oauth ./bin/vact sheets preflight && ./bin/vact sheets push")


@sheets_app.command("preflight")
def sheets_preflight_cmd() -> None:
    """Authenticate and verify the account can read the target sheet."""
    from vact.exports import sheets as sheets_mod

    try:
        result = sheets_mod.preflight()
    except sheets_mod.SheetsConfigError as err:
        typer.echo(str(err), err=True)
        raise typer.Exit(code=2) from err
    except RuntimeError as err:
        typer.echo(str(err), err=True)
        raise typer.Exit(code=1) from err
    typer.echo(
        f"Sheets preflight ok: {result['spreadsheet']} "
        f"(auth={result.get('auth')} account={result.get('account')})"
    )


@sheets_app.command("push")
def sheets_push_cmd(
    warehouse: Path | None = typer.Option(None, "--warehouse"),
) -> None:
    """Push README, Target Four, Full Delegation, and Vote Detail tabs."""
    from vact.exports import sheets as sheets_mod

    try:
        counts = sheets_mod.push(warehouse_path=warehouse)
    except sheets_mod.SheetsConfigError as err:
        typer.echo(str(err), err=True)
        raise typer.Exit(code=2) from err
    except RuntimeError as err:
        typer.echo(str(err), err=True)
        raise typer.Exit(code=1) from err
    for tab, n in counts.items():
        typer.echo(f"  {tab}: {n} rows")
    typer.echo("Sheets push complete.")


@app.command("site")
def site_cmd(
    out: Path | None = typer.Option(None, "--out", help="Output directory (default docs/)."),
    warehouse: Path | None = typer.Option(None, "--warehouse"),
    map_version: str = typer.Option("2026", "--map-version"),
) -> None:
    """Build the activist static site into docs/ (GitHub Pages)."""
    from vact.exports.site import build_site

    dest = build_site(out_dir=out, warehouse_path=warehouse, map_version=map_version)
    typer.echo(f"Site built → {dest}")


@app.command("export-web")
def export_web_cmd(
    map_version: str = typer.Option("2021", "--map-version", help="Operative map (default 2021)."),
    out: Path | None = typer.Option(None, "--out", help="Output dir (default web/data/)."),
    warehouse: Path | None = typer.Option(None, "--warehouse"),
    from_warehouse: bool = typer.Option(
        False,
        "--from-warehouse",
        help="Score from DuckDB instead of data/votes.csv (bootstrap / identity check).",
    ),
    votes: Path | None = typer.Option(None, "--votes", help="Path to votes.csv."),
) -> None:
    """Export analysis JSON (scores, deviations, delegation) for the Next.js dashboard."""
    from vact.exports.web import export_web

    paths = export_web(
        map_version=map_version,
        out_dir=out,
        warehouse_path=warehouse,
        votes_path=votes,
        from_warehouse=from_warehouse,
    )
    for p in paths:
        typer.echo(f"  wrote {p}")
    typer.echo(f"Exported {len(paths)} JSON files for the web app.")


@app.command("irt")
def irt_cmd(
    votes: Path | None = typer.Option(None, "--votes", help="Path to votes.csv."),
    out: Path | None = typer.Option(None, "--out", help="Output JSON (default data/derived/irt.json)."),
    no_web: bool = typer.Option(False, "--no-web", help="Do not copy the artifact to web/data/irt.json."),
    draws: int | None = typer.Option(None, "--draws", help="Override NUTS draws."),
    tune: int | None = typer.Option(None, "--tune", help="Override NUTS tune."),
) -> None:
    """Fit the offline 2PL IRT model and write data/derived/irt.json."""
    from vact.analysis.irt_pipeline import run_irt

    payload = run_irt(
        votes_path=votes,
        out_path=out,
        copy_web=not no_web,
        draws=draws,
        tune=tune,
        progressbar=True,
    )
    typer.echo(
        f"IRT 2PL: {payload['n_members']} members, {payload['n_items']} items, "
        f"R-hat max {payload['rhat_max']}, ESS min {payload['ess_bulk_min']}"
    )
    typer.echo(f"anchors {payload['identification']['low_anchor']} → {payload['identification']['high_anchor']}")


@cosp_app.command("fetch")
def cosp_fetch_cmd(
    api_key: str = typer.Option(None, "--api-key", envvar="CONGRESS_API_KEY"),
    congress: int | None = typer.Option(None, "--congress"),
    force: bool = typer.Option(False, "--force", help="Re-fetch cached member pages."),
    from_raw: bool = typer.Option(False, "--from-raw", help="Parse cached raw pages only (no network)."),
) -> None:
    """Fetch VA (co)sponsorship lists and merge data/bills_candidates.csv."""
    from vact.pipeline.cosponsorship import ingest_cosponsorship

    stats = ingest_cosponsorship(
        api_key=api_key, congress=congress, force=force, from_raw=from_raw
    )
    typer.echo(
        "Cosponsorship ingest: "
        f"members={stats['members']} bills={stats['bills_seen']} "
        f"candidates={stats['candidates']} adjudicated={stats['adjudicated']} "
        f"actions={stats['actions']}"
    )


@cosp_app.command("validate")
def cosp_validate_cmd() -> None:
    """Validate bills_candidates.csv."""
    from vact.analysis.bills_candidates import validate_candidates_file

    rows = validate_candidates_file()
    typer.echo(f"bills_candidates.csv ok ({len(rows)} rows)")


@races_app.command("validate")
def races_validate_cmd() -> None:
    """Validate data/races.json schema and tracked-race requirements."""
    from vact.analysis.races import validate_races

    reg = validate_races()
    typer.echo(
        f"races.json ok ({len(reg.races)} races, election {reg.election_date.isoformat()}, "
        f"map_version={reg.map_version})"
    )


@fec_app.command("snapshot")
def fec_snapshot_cmd(
    api_key: str = typer.Option(None, "--api-key", envvar="FEC_API_KEY"),
    cycle: int = typer.Option(2026, "--cycle"),
    force: bool = typer.Option(False, "--force", help="Re-fetch and overwrite today's snapshot."),
) -> None:
    """Write data/derived/fec_YYYYMMDD.json for all tracked candidates. Same-day re-run is a no-op."""
    from vact.pipeline.fec import snapshot_fec

    if not api_key:
        raise typer.BadParameter("set FEC_API_KEY (e.g. in .env) or pass --api-key")
    result = snapshot_fec(api_key=api_key, cycle=cycle, force=force)
    tag = "no-op" if result["noop"] else "wrote"
    typer.echo(f"FEC snapshot {tag}: {result['path']} ({result['n_candidates']} candidates)")


@seats_app.command("build-train")
def seats_build_train_cmd(
    medsl: Path = typer.Option(
        Path("data/raw/medsl/house_1976_2022.csv"),
        "--medsl",
        help="MEDSL / TidyTuesday house candidate CSV.",
    ),
) -> None:
    """Collapse MEDSL candidate rows into the committed training extract."""
    from vact.analysis.seat_train import build_training_csv_from_medsl

    path = build_training_csv_from_medsl(medsl)
    typer.echo(f"wrote {path}")


@seats_app.command("fit")
def seats_fit_cmd() -> None:
    """Fit OLS/logit on the committed training extract and write the fit summary."""
    from vact.analysis.seat_model import fit_seat_model, write_fit

    summary = fit_seat_model()
    path = write_fit(summary)
    typer.echo(
        f"fit {summary['model_version']}: n_train={summary['n_train']} "
        f"holdout_brier={summary['holdout_brier']:.4f} "
        f"always_inc_brier={summary['holdout_always_incumbent_brier']:.4f} → {path}"
    )


@seats_app.command("predict")
def seats_predict_cmd() -> None:
    """Score tracked races, append predictions_seats.csv, refresh web JSON payload."""
    from vact.analysis.seat_model import append_predictions, predict_races
    from vact.paths import DATA_DIR

    payload = predict_races()
    log_path = append_predictions(payload)
    dest = DATA_DIR.parent / "web" / "data" / "seats.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    typer.echo(
        f"seats {payload['model_version']} as_of={payload['as_of']} "
        f"n={len(payload['races'])} log={log_path}"
    )


@seats_app.command("validate")
def seats_validate_cmd() -> None:
    """Validate the append-only predictions log and spec/version freeze."""
    from vact.analysis.seat_model import (
        CONFIG_PATH,
        SPEC_PATH,
        load_fit,
        load_seat_config,
        validate_predictions_file,
    )

    cfg = load_seat_config()
    if not SPEC_PATH.is_file():
        raise typer.Exit(f"missing spec {SPEC_PATH}")
    fit = load_fit()
    if fit["model_version"] != cfg["model_version"]:
        raise typer.Exit("fit model_version does not match config")
    rows = validate_predictions_file()
    typer.echo(
        f"seats ok version={cfg['model_version']} predictions={len(rows)} spec={SPEC_PATH.name}"
    )


@app.command("social")
def social_cmd(
    out: Path | None = typer.Option(None, "--out", help="PNG output directory."),
    warehouse: Path | None = typer.Option(None, "--warehouse"),
) -> None:
    """Generate 1200×675 social cards for the Target Four districts."""
    from vact.exports.social import build_social_cards

    paths = build_social_cards(out_dir=out, warehouse_path=warehouse)
    for path in paths:
        typer.echo(str(path))
    typer.echo(f"Wrote {len(paths)} social cards.")


@valence_app.command("propose")
def valence_propose_cmd(
    all_: bool = typer.Option(
        False,
        "--all",
        help="Re-propose even for pairs that already carry a valence.",
    ),
    warehouse: Path | None = typer.Option(None, "--warehouse"),
) -> None:
    """Write RULE-proposed valence from config (PROPOSALS — promote to HUMAN before publishing)."""
    from vact.analysis.scoring import load_scoring_config, propose_valence

    conn = connect(warehouse)
    try:
        ensure_schema(conn)
        stats = propose_valence(conn, load_scoring_config(), new_only=not all_)
    finally:
        conn.close()
    typer.echo(
        "Valence propose complete: "
        f"proposed={stats['proposed']} "
        f"skipped_existing={stats['skipped_existing']} "
        f"unmatched={stats['unmatched']}"
    )


@valence_app.command("set", context_settings={"ignore_unknown_options": True})
def valence_set_cmd(
    vote_id: str = typer.Argument(..., help="fact_vote.vote_id, e.g. h-119-1-156"),
    impact_tag: str = typer.Argument(..., help="Impact tag, e.g. FEDERAL_CONTRACTING"),
    valence: int = typer.Argument(..., help="+1 pro-axis on YEA, -1 anti-axis, 0 not scoreable"),
    warehouse: Path | None = typer.Option(None, "--warehouse"),
) -> None:
    """Record a human-adjudicated valence (classified_by=HUMAN)."""
    from vact.analysis.scoring import set_valence

    conn = connect(warehouse)
    try:
        ensure_schema(conn)
        set_valence(
            conn, vote_id=vote_id, impact_tag=impact_tag, valence=valence, source="HUMAN"
        )
    finally:
        conn.close()
    typer.echo(f"Set valence[{vote_id}, {impact_tag}] = {valence:+d} (HUMAN).")


@app.command("deviations")
def deviations_cmd(
    map_version: str = typer.Option("2021", "--map-version", help="Operative map (default 2021)."),
    warehouse: Path | None = typer.Option(None, "--warehouse"),
    from_warehouse: bool = typer.Option(
        False, "--from-warehouse", help="Read DuckDB instead of data/votes.csv."
    ),
    votes: Path | None = typer.Option(None, "--votes", help="Path to votes.csv."),
) -> None:
    """Within-party deviation report (defection detection) → reports/party_deviations.md."""
    from vact.analysis.deviations import (
        compute_party_deviations,
        write_deviations_report,
    )
    from vact.analysis.scoring import load_scoring_config
    from vact.analysis.votes import resolve_votes_path

    csv_path = None if from_warehouse else resolve_votes_path(votes)
    conn = connect(warehouse)
    try:
        ensure_schema(conn)
        rows = compute_party_deviations(
            conn, load_scoring_config(), map_version=map_version, votes_path=csv_path
        )
    finally:
        conn.close()
    dest = write_deviations_report(
        map_version=map_version, warehouse_path=warehouse, votes_path=csv_path
    )
    typer.echo(f"Deviations report → {dest} ({len(rows)} member-theme deviations)")
    for r in rows[:8]:
        typer.echo(
            f"  {r.full_name:<22} {r.impact_tag:<18} dev={r.deviation:+.2f} "
            f"({len(r.defection_votes)} defection votes)"
        )


@app.command("score")
def score_cmd(
    map_version: str = typer.Option("2021", "--map-version", help="Operative map (default 2021)."),
    write: bool = typer.Option(
        False, "--write", help="Also write data/reports/scores_frame.csv."
    ),
    warehouse: Path | None = typer.Option(None, "--warehouse"),
    from_warehouse: bool = typer.Option(
        False, "--from-warehouse", help="Read DuckDB instead of data/votes.csv."
    ),
    votes: Path | None = typer.Option(None, "--votes", help="Path to votes.csv."),
) -> None:
    """Build the live signed scoring frame (per member × theme) and summarize it."""
    import csv as _csv

    from vact.analysis.scoring import build_scores_frame, load_scoring_config
    from vact.analysis.votes import resolve_votes_path
    from vact.transforms.classify import REPORTS_DIR

    csv_path = None if from_warehouse else resolve_votes_path(votes)
    conn = connect(warehouse)
    try:
        ensure_schema(conn)
        cfg = load_scoring_config()
        frame = build_scores_frame(conn, cfg, map_version=map_version, votes_path=csv_path)
        rule_valence = conn.execute(
            "SELECT count(*) FROM fact_vote_valence WHERE valence_source = 'RULE'"
        ).fetchone()
    finally:
        conn.close()

    if not frame:
        typer.echo(
            "Scoring frame is empty. Adjudicate valence first: "
            "`vact valence propose` then review, or `vact valence set ...`."
        )
        return

    sufficient = [r for r in frame if r["sufficient"]]
    typer.echo(
        f"Scoring frame (map {map_version}): {len(frame)} member×theme cells, "
        f"{len(sufficient)} sufficient (n_contested ≥ {cfg.min_contested})."
    )
    if rule_valence and int(rule_valence[0]) > 0:
        typer.echo(
            f"⚠  {int(rule_valence[0])} valence rows are un-promoted RULE proposals — "
            "review and `vact valence set` before publishing a scorecard."
        )
    top = sorted(
        (r for r in sufficient if r["signed_score"] is not None),
        key=lambda r: abs(r["signed_score"]),
        reverse=True,
    )[:10]
    for r in top:
        typer.echo(
            f"  {r['full_name']:<22} {r['impact_tag']:<20} "
            f"score={r['signed_score']:+.2f} "
            f"[{r['wilson_low']:+.2f},{r['wilson_high']:+.2f}] "
            f"{r['n_yea']}Y/{r['n_nay']}N n={r['n_contested']}"
        )

    if write:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        out = REPORTS_DIR / "scores_frame.csv"
        fieldnames = list(frame[0].keys())
        with out.open("w", newline="", encoding="utf-8") as fh:
            writer = _csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(frame)
        typer.echo(f"Wrote {out}")


@votes_app.command("export")
def votes_export_cmd(
    map_version: str = typer.Option("2021", "--map-version", help="Operative map (default 2021)."),
    warehouse: Path | None = typer.Option(None, "--warehouse"),
    out: Path | None = typer.Option(None, "--out", help="Output CSV (default data/votes.csv)."),
) -> None:
    """Export scoreable warehouse rows to versioned data/votes.csv + diff report."""
    from vact.analysis.votes import DIFF_REPORT_PATH, export_votes_csv

    path, diff = export_votes_csv(
        map_version=map_version, warehouse_path=warehouse, out_path=out
    )
    typer.echo(f"Wrote {path} ({diff['n_current']} rows)")
    typer.echo(
        f"Diff vs previous: +{len(diff['added'])} −{len(diff['removed'])} "
        f"~{len(diff['changed'])} → {DIFF_REPORT_PATH}"
    )


@votes_app.command("validate")
def votes_validate_cmd(
    votes: Path | None = typer.Option(None, "--votes", help="Path to votes.csv."),
) -> None:
    """Fail loud if data/votes.csv is malformed."""
    from vact.analysis.votes import VOTES_CSV_PATH, validate_votes_csv

    rows = validate_votes_csv(votes or VOTES_CSV_PATH)
    typer.echo(f"votes.csv ok: {len(rows)} rows")


@votes_app.command("diff")
def votes_diff_cmd(
    votes: Path | None = typer.Option(None, "--votes", help="Path to votes.csv."),
) -> None:
    """Diff working tree votes.csv against HEAD."""
    from vact.analysis.votes import (
        DIFF_REPORT_PATH,
        VOTES_CSV_PATH,
        diff_vote_rows,
        load_committed_votes_csv,
        load_votes_csv,
        render_votes_diff_md,
        validate_votes_csv,
    )

    current = validate_votes_csv(votes or VOTES_CSV_PATH)
    previous = load_committed_votes_csv() or []
    diff = diff_vote_rows(previous, current)
    DIFF_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DIFF_REPORT_PATH.write_text(render_votes_diff_md(diff), encoding="utf-8")
    typer.echo(
        f"HEAD vs {votes or VOTES_CSV_PATH}: +{len(diff['added'])} "
        f"−{len(diff['removed'])} ~{len(diff['changed'])} → {DIFF_REPORT_PATH}"
    )


@votes_app.command("sync")
def votes_sync_cmd(
    map_version: str = typer.Option("2021", "--map-version", help="Operative map (default 2021)."),
    warehouse: Path | None = typer.Option(None, "--warehouse"),
    out: Path | None = typer.Option(None, "--out", help="Output CSV (default data/votes.csv)."),
    sheets: bool = typer.Option(
        False, "--sheets", help="Also write a read-only Vote Detail coverage diff."
    ),
) -> None:
    """Export from warehouse, validate, optional Sheets reconciliation (not a source)."""
    from vact.analysis.votes import SHEETS_DIFF_PATH, sync_votes

    result = sync_votes(
        map_version=map_version,
        warehouse_path=warehouse,
        out_path=out,
        sheets=sheets,
    )
    diff = result["diff"]
    typer.echo(f"Synced {result['path']} ({result['n']} rows)")
    typer.echo(
        f"Diff: +{len(diff['added'])} −{len(diff['removed'])} ~{len(diff['changed'])}"
    )
    if sheets:
        recon = result["sheets"] or {}
        if recon.get("skipped"):
            typer.echo(f"Sheets recon skipped: {recon.get('reason')}")
        else:
            typer.echo(
                f"Sheets coverage: csv_only={len(recon['only_csv'])} "
                f"sheet_only={len(recon['only_sheet'])} → {SHEETS_DIFF_PATH}"
            )


if __name__ == "__main__":
    app()
